"""
UploadService — the Document Upload Pipeline (Phase 6).

Owns the ENTIRE upload policy; routes stay logic-free and adapters stay dumb.
For every incoming file the service, in order:

  1. rejects a missing/blank filename or empty body            -> 400 empty_file
  2. checks the extension against the allowlist                -> 415 unsupported_file_type
  3. checks the declared MIME type against the extension       -> 415 unsupported_file_type
  4. streams the body in 1 MB chunks, aborting past the cap    -> 413 file_too_large
  5. sniffs the content's magic bytes (never trust the client) -> 415 unsupported_file_type
  6. generates document_id (uuid4) + stored filename <uuid><ext>
  7. persists bytes via the FileStorage port (local disk today, S3 later)
  8. registers metadata via the DocumentRepository port        -> 409 on id collision

Only PDF, JPG, JPEG, and PNG are accepted. The original filename is kept purely
as display metadata — the file on disk is always named after the UUID, so a
hostile filename ("../../evil.exe", "CON.pdf", 300-char unicode…) can never
influence storage.
"""

import logging
import uuid
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import UploadFile

from app.core.config import Settings, settings
from app.core.exceptions import (
    DocumentNotFoundError,
    EmptyUploadError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.domain.document import UploadedDocument
from app.domain.enums import DocumentCategory
from app.domain.repositories import DocumentRepository, FileStorage

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Upload policy tables — the single source of truth for what is accepted.
# --------------------------------------------------------------------------- #

# extension -> (canonical MIME type stored in metadata, storage category)
_ALLOWED_EXTENSIONS: dict[str, tuple[str, DocumentCategory]] = {
    ".pdf": ("application/pdf", DocumentCategory.PDF),
    ".jpg": ("image/jpeg", DocumentCategory.IMAGE),
    ".jpeg": ("image/jpeg", DocumentCategory.IMAGE),
    ".png": ("image/png", DocumentCategory.IMAGE),
}

# extension -> MIME types a client may legitimately declare for it. Anything
# else (application/octet-stream included) is rejected: an honest client for
# these four types always knows the real MIME.
_ALLOWED_MIME_BY_EXTENSION: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".jpg": frozenset({"image/jpeg", "image/jpg"}),
    ".jpeg": frozenset({"image/jpeg", "image/jpg"}),
    ".png": frozenset({"image/png"}),
}

# extension -> magic-byte signatures the file content must actually start with.
# This is what catches an .exe renamed to invoice.pdf — the declared name and
# MIME both lie, but the first bytes cannot.
_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}

# Stream uploads in 1 MB chunks so a 10 GB body is rejected after reading
# ~11 MB, not after buffering the whole thing.
_CHUNK_SIZE = 1024 * 1024


def _sanitize_original_filename(raw: str) -> str:
    """
    Reduce a client filename to its final path component.

    Browsers send bare names, but nothing stops a crafted client from sending
    'C:\\evil\\..\\x.pdf' or '../../x.pdf'. Both path flavors are stripped; the
    result is used ONLY as display metadata anyway.
    """
    name = PureWindowsPath(raw).name          # strips both '\\' segments and drive letters
    name = PurePosixPath(name.replace("\\", "/")).name  # then any remaining '/' segments
    return name.strip()


class UploadService:
    """Application service orchestrating validation, storage, and metadata."""

    def __init__(
        self,
        repository: DocumentRepository,
        storage: FileStorage,
        config: Settings = settings,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        self._max_mb = config.MAX_UPLOAD_SIZE_MB

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    async def store_upload(self, upload: UploadFile) -> UploadedDocument:
        """Validate an incoming file end-to-end, persist it, and return its record."""
        original_filename = _sanitize_original_filename(upload.filename or "")
        if not original_filename:
            raise EmptyUploadError("No file was provided (missing filename).")

        extension = self._validated_extension(original_filename)
        self._validated_mime(extension, upload.content_type)
        content = await self._read_within_limit(upload)
        self._validated_signature(extension, content)

        canonical_mime, category = _ALLOWED_EXTENSIONS[extension]
        document_id = str(uuid.uuid4())
        stored_filename = f"{document_id}{extension}"

        # Bytes first, metadata second: a crash between the two leaves an
        # orphaned file (harmless), never a metadata record pointing nowhere.
        self._storage.save(category, stored_filename, content)
        document = UploadedDocument(
            document_id=document_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            content_type=canonical_mime,
            file_size=len(content),
            category=category,
        )
        try:
            self._repository.add(document)  # raises DuplicateDocumentError on collision
        except Exception:
            # Roll back the stored bytes so a failed registration leaves no trace.
            self._storage.delete(category, stored_filename)
            raise

        logger.info(
            "Upload stored: id=%s name=%r type=%s size=%d",
            document_id, original_filename, canonical_mime, len(content),
        )
        return document

    def delete_document(self, document_id: str) -> UploadedDocument:
        """Remove a document's bytes and metadata; return the deleted record."""
        document = self.get_document(document_id)
        self._storage.delete(document.category, document.stored_filename)
        self._repository.delete(document_id)
        logger.info("Upload deleted: id=%s", document_id)
        return document

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def get_document(self, document_id: str) -> UploadedDocument:
        """Return one document's metadata or raise a typed 404."""
        document = self._repository.get(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return document

    def list_documents(self) -> tuple[UploadedDocument, ...]:
        """Return metadata for every stored document, newest first."""
        return self._repository.list_all()

    # ------------------------------------------------------------------ #
    # Validation steps (each raises a typed DomainError on failure)
    # ------------------------------------------------------------------ #

    def _validated_extension(self, filename: str) -> str:
        extension = PurePosixPath(filename).suffix.lower()
        if extension not in _ALLOWED_EXTENSIONS:
            shown = extension or "no extension"
            raise UnsupportedFileTypeError(f"extension '{shown}' is not allowed.")
        return extension

    def _validated_mime(self, extension: str, declared_mime: str | None) -> None:
        mime = (declared_mime or "").split(";")[0].strip().lower()
        if mime not in _ALLOWED_MIME_BY_EXTENSION[extension]:
            raise UnsupportedFileTypeError(
                f"MIME type '{mime or 'unknown'}' does not match a '{extension}' file."
            )

    async def _read_within_limit(self, upload: UploadFile) -> bytes:
        """Stream the body, failing fast the moment it exceeds the size cap."""
        chunks: list[bytes] = []
        total = 0
        while chunk := await upload.read(_CHUNK_SIZE):
            total += len(chunk)
            if total > self._max_bytes:
                raise FileTooLargeError(self._max_mb)
            chunks.append(chunk)
        if total == 0:
            raise EmptyUploadError()
        return b"".join(chunks)

    def _validated_signature(self, extension: str, content: bytes) -> None:
        """Verify the file REALLY is what its name claims, via magic bytes."""
        if not any(content.startswith(sig) for sig in _MAGIC_SIGNATURES[extension]):
            raise UnsupportedFileTypeError(
                f"file content does not match a real '{extension}' file."
            )
