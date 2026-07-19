"""
AssetService — the photograph/signature a KYC form requires.

Deliberately NOT a second state machine. An asset is stored, then written into
the interview session as an ordinary answer on an ordinary field
(`applicant_photo` / `applicant_signature`) through the ordinary
SessionService path. Everything downstream — progress %, the next question,
the PDF completion gate, the "pending" badge — is then computed by the SAME
recompute that already runs for every other field. There is no separate
"asset progress" to keep in sync, because there is no second source of truth.

Upload policy, per kind:

    photo      JPG/JPEG/PNG, <= 5 MB
    signature  JPG/JPEG/PNG, <= 2 MB

Every upload is checked three ways — declared MIME, byte size, and actual
decodability — because a file can pass the first two and still be a truncated
image that only fails at PDF-generation time.

An asset is refused outright when the active form does not require it: there
would be nowhere to place it.
"""

import logging
import uuid

from app.core.exceptions import (
    AssetNotFoundError,
    AssetNotRequiredError,
    AssetTooLargeError,
    InvalidAssetError,
)
from app.domain.enums import DocumentCategory
from app.domain.form_assets import (
    ASSET_ALLOWED_MIME,
    ASSET_FIELD_IDS,
    ASSET_MAX_BYTES,
    AssetKind,
    SessionAsset,
)
from app.domain.repositories import FileStorage, SessionAssetRepository
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

# Magic bytes — the only check a hostile client cannot lie about.
_MAGIC: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
)


class AssetService:
    """Store, validate, and retract a session's photograph/signature."""

    def __init__(
        self,
        repository: SessionAssetRepository,
        storage: FileStorage,
        sessions: SessionService,
        intelligence=None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._sessions = sessions
        # Optional: consulted for "does the active form require this?" and to
        # re-sync after a change. None (isolated tests) simply skips the gate.
        self._intelligence = intelligence

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    def store(
        self,
        session_id: str,
        kind: AssetKind,
        filename: str,
        declared_mime: str | None,
        content: bytes,
    ) -> SessionAsset:
        """
        Validate and store one asset, then answer its interview field.

        Replaces any existing asset of the same kind (a session has one photo
        and one signature, never a pile of attempts). Raises the typed 422/413
        for bad content and 404 for an unknown session.
        """
        self._sessions.get_session(session_id)  # typed 404 before any work
        self._require_asset_wanted(session_id, kind)

        canonical_mime, extension = self._validated_content(kind, declared_mime, content)
        width, height = self._validated_decodable(kind, content)

        # Replace: drop the previous file so a session never leaves orphans.
        previous = self._repository.get(session_id, kind)
        if previous is not None:
            self._storage.delete(DocumentCategory.IMAGE, previous.stored_filename)

        asset_id = uuid.uuid4().hex
        stored_filename = f"asset-{asset_id}{extension}"
        self._storage.save(DocumentCategory.IMAGE, stored_filename, content)

        asset = SessionAsset(
            asset_id=asset_id,
            session_id=session_id,
            kind=kind,
            original_filename=filename.strip()[:200] or f"{kind.value}{extension}",
            stored_filename=stored_filename,
            content_type=canonical_mime,
            file_size=len(content),
            width=width,
            height=height,
        )
        self._repository.save(asset)

        # The ONE sync point: the asset id becomes the field's answer, and the
        # normal refresh recomputes progress, the next question and the PDF
        # gate. Nothing else needs telling.
        self._sessions.update_answer(session_id, ASSET_FIELD_IDS[kind], asset_id)
        self._resync(session_id)

        logger.info(
            "Asset stored: session=%s kind=%s size=%d (%dx%d)",
            session_id, kind.value, len(content), width, height,
        )
        return asset

    def delete(self, session_id: str, kind: AssetKind) -> SessionAsset:
        """
        Remove an asset and return its field to PENDING.

        `clear_answer` (not a blank submission) is used on purpose: it erases
        the field from BOTH the answers and the error map, so a required photo
        reads as "Pending" again rather than "Invalid".
        """
        asset = self._repository.get(session_id, kind)
        if asset is None:
            raise AssetNotFoundError(kind.value)
        self._storage.delete(DocumentCategory.IMAGE, asset.stored_filename)
        self._repository.delete(session_id, kind)
        self._sessions.clear_answer(session_id, ASSET_FIELD_IDS[kind])
        self._resync(session_id)
        logger.info("Asset deleted: session=%s kind=%s", session_id, kind.value)
        return asset

    def forget_session(self, session_id: str) -> None:
        """Drop every asset a session holds (used when the session is deleted)."""
        for asset in self._repository.list_for_session(session_id):
            self._storage.delete(DocumentCategory.IMAGE, asset.stored_filename)
            self._repository.delete(session_id, asset.kind)

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def get(self, session_id: str, kind: AssetKind) -> SessionAsset | None:
        """The session's asset of this kind, or None."""
        return self._repository.get(session_id, kind)

    def list_for_session(self, session_id: str) -> tuple[SessionAsset, ...]:
        """Every asset this session holds."""
        return self._repository.list_for_session(session_id)

    def read_bytes(self, asset: SessionAsset) -> bytes:
        """The stored image bytes. Raises the typed 404 if the file vanished."""
        try:
            return self._storage.read(DocumentCategory.IMAGE, asset.stored_filename)
        except FileNotFoundError as exc:
            raise AssetNotFoundError(asset.kind.value) from exc

    def bytes_for(self, session_id: str, kind: AssetKind) -> bytes | None:
        """
        The image bytes for one kind, or None when absent/unreadable.

        Used by PDF generation, which must never fail because a signature file
        went missing — it simply produces the form without it.
        """
        asset = self._repository.get(session_id, kind)
        if asset is None:
            return None
        try:
            return self.read_bytes(asset)
        except AssetNotFoundError:
            logger.warning("Asset file missing on disk for session %s", session_id)
            return None

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def _require_asset_wanted(self, session_id: str, kind: AssetKind) -> None:
        """Refuse an asset the ACTIVE form has no place for."""
        if self._intelligence is None:
            return
        requirements = self._intelligence.asset_requirements(session_id)
        if requirements is None or not requirements.requires(kind):
            raise AssetNotRequiredError(kind.value)

    @staticmethod
    def _validated_content(
        kind: AssetKind, declared_mime: str | None, content: bytes
    ) -> tuple[str, str]:
        """Check emptiness, size cap, declared MIME and real magic bytes."""
        if not content:
            raise InvalidAssetError(f"The {kind.value} file is empty.")

        cap = ASSET_MAX_BYTES[kind]
        if len(content) > cap:
            raise AssetTooLargeError(kind.value, cap / (1024 * 1024))

        mime = (declared_mime or "").split(";")[0].strip().lower()
        if mime not in ASSET_ALLOWED_MIME:
            raise InvalidAssetError(
                f"A {kind.value} must be a JPG or PNG image "
                f"(received '{mime or 'unknown'}')."
            )

        for signature, canonical_mime, extension in _MAGIC:
            if content.startswith(signature):
                return canonical_mime, extension
        raise InvalidAssetError(
            f"That file is not a real JPG or PNG image — please re-export your "
            f"{kind.value} and try again."
        )

    @staticmethod
    def _validated_decodable(kind: AssetKind, content: bytes) -> tuple[int, int]:
        """
        Confirm the image actually DECODES, and return its pixel size.

        A correct header proves nothing about the rest of the file. Without
        this, a truncated upload is accepted happily and only explodes when the
        PDF is generated — long after the user has moved on.

        Pillow with an explicit `load()` is used rather than PyMuPDF's Pixmap
        because Pixmap is LAZY: given a 40-byte fragment it happily reports the
        dimensions from the PNG header and never touches the (missing) pixel
        data, so a truncated file passes. `load()` forces the full decode, which
        is the only thing that actually proves the image is intact.
        """
        try:
            import io

            from PIL import Image

            image = Image.open(io.BytesIO(content))
            image.load()  # forces a real decode — lazy checks are not enough
            width, height = image.size
        except Exception as exc:  # noqa: BLE001
            raise InvalidAssetError(
                f"That {kind.value} image could not be read — it may be "
                "corrupted or incomplete. Please try another file."
            ) from exc
        if width < 1 or height < 1:
            raise InvalidAssetError(f"That {kind.value} image has no content.")
        return width, height

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _resync(self, session_id: str) -> None:
        """
        Re-run the authoritative recompute after an asset change.

        Best-effort: the session answer is already written, so a profile that
        fails to re-merge must not fail the upload.
        """
        if self._intelligence is None:
            return
        try:
            self._intelligence.get_profile(session_id)
        except Exception:  # noqa: BLE001
            logger.warning("Profile re-sync after asset change failed for %s", session_id)
