"""
Local-filesystem adapter for the FileStorage port (Phase 6).

Stores uploaded bytes under a root directory (default `backend/uploads/`) with
one subdirectory per DocumentCategory:

    uploads/
    ├── pdf/       # application/pdf
    └── images/    # image/jpeg, image/png

Design notes:
  * Implements the abstract FileStorage port — an S3 adapter later implements
    the same four methods and swaps in via core/dependencies.py; the
    UploadService never knows which backend it is talking to.
  * `stored_filename` is ALWAYS server-generated upstream (uuid + extension),
    but this adapter still defends itself: any path separator or parent
    reference in a filename is rejected outright, so a path-traversal name can
    never escape the root even if a future caller misbehaves.
  * Writes are atomic-enough for the MVP: bytes are written to the final path
    in one call; there is no partial-file window observable through the API
    because metadata is only registered after `save()` returns.
"""

import logging
from pathlib import Path

from app.domain.enums import DocumentCategory
from app.domain.repositories import FileStorage

logger = logging.getLogger(__name__)

# Category -> subdirectory beneath the storage root.
_CATEGORY_DIRS: dict[DocumentCategory, str] = {
    DocumentCategory.PDF: "pdf",
    DocumentCategory.IMAGE: "images",
}


class LocalStorageAdapter(FileStorage):
    """FileStorage implementation backed by the local filesystem."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        # Create the full directory tree up front so the first upload never
        # races directory creation.
        for subdir in _CATEGORY_DIRS.values():
            (self._root / subdir).mkdir(parents=True, exist_ok=True)
        logger.info("LocalStorageAdapter root: %s", self._root)

    # ------------------------------------------------------------------ #
    # FileStorage port
    # ------------------------------------------------------------------ #

    def save(self, category: DocumentCategory, stored_filename: str, content: bytes) -> str:
        path = self._path(category, stored_filename)
        path.write_bytes(content)
        logger.info("Stored %d bytes at %s", len(content), path)
        return str(path)

    def read(self, category: DocumentCategory, stored_filename: str) -> bytes:
        return self._path(category, stored_filename).read_bytes()

    def delete(self, category: DocumentCategory, stored_filename: str) -> bool:
        path = self._path(category, stored_filename)
        if not path.is_file():
            return False
        path.unlink()
        logger.info("Deleted stored file %s", path)
        return True

    def exists(self, category: DocumentCategory, stored_filename: str) -> bool:
        return self._path(category, stored_filename).is_file()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _path(self, category: DocumentCategory, stored_filename: str) -> Path:
        """Resolve a stored filename to its on-disk path, refusing traversal."""
        # Defense in depth: stored filenames are uuid-based by construction,
        # but never allow one to point outside its category directory.
        if Path(stored_filename).name != stored_filename or stored_filename in {"", ".", ".."}:
            raise ValueError(f"Illegal stored filename: {stored_filename!r}")
        return self._root / _CATEGORY_DIRS[category] / stored_filename
