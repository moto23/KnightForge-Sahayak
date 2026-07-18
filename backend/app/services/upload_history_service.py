"""
UploadHistoryService (Phase 13) — persistent, per-user upload audit trail.

A thin recorder AROUND the existing upload pipeline, never inside it:
UploadService keeps owning validation/storage; this service only journals
what happened (who uploaded what, the declared document type, and how far
the document travelled through OCR → prefill) into SQLite so history
survives restarts and follows the signed-in user across devices.

Every mutation is best-effort by design: history must never be able to fail
an upload or an OCR run, so callers wrap these in try/except at the route
layer and the workflow proceeds regardless.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import UploadHistory

logger = logging.getLogger(__name__)

# The user-facing document types selectable BEFORE upload. Kept as a plain
# allowlist (not an enum in business logic) — unknown values degrade to
# "other" instead of failing the upload.
ALLOWED_DOCUMENT_TYPES = frozenset(
    {
        "kyc_form",
        "pan_card",
        "aadhaar_card",
        "passport",
        "driving_licence",
        "bank_statement",
        "utility_bill",
        "other",
    }
)


def normalize_document_type(raw: str | None) -> str:
    """Reduce a client-declared type to a known slug (fallback: 'other')."""
    slug = (raw or "").strip().lower()
    return slug if slug in ALLOWED_DOCUMENT_TYPES else "other"


class UploadHistoryService:
    """CRUD over upload_history rows, bound to one request's DB session."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    def record_upload(
        self,
        *,
        document_id: str,
        filename: str,
        document_type: str,
        file_size: int,
        user_id: str | None,
    ) -> UploadHistory:
        """Journal a fresh upload (guest uploads carry user_id=None)."""
        row = UploadHistory(
            document_id=document_id,
            filename=filename,
            document_type=normalize_document_type(document_type),
            file_size=file_size,
            user_id=user_id,
        )
        self._db.add(row)
        self._db.commit()
        return row

    def mark_ocr(self, document_id: str, *, ok: bool) -> None:
        """OCR finished (or failed) for a document — update both statuses."""
        row = self._get(document_id)
        if row is None:
            return
        row.ocr_status = "completed" if ok else "failed"
        if ok and row.processing_status == "uploaded":
            row.processing_status = "analyzed"
        self._db.commit()

    def mark_processed(self, document_id: str, detected_type: str | None = None) -> None:
        """Document's values were merged/prefilled into an interview session."""
        row = self._get(document_id)
        if row is None:
            return
        row.processing_status = "prefilled"
        if detected_type:
            row.detected_type = detected_type
        self._db.commit()

    def mark_deleted(self, document_id: str) -> None:
        """Document removed — keep the audit row, flip its status."""
        row = self._get(document_id)
        if row is None:
            return
        row.processing_status = "deleted"
        self._db.commit()

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def list_for_user(self, user_id: str, limit: int = 50) -> list[UploadHistory]:
        """The caller's uploads, newest first (deleted rows included)."""
        stmt = (
            select(UploadHistory)
            .where(UploadHistory.user_id == user_id)
            .order_by(UploadHistory.uploaded_at.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def _get(self, document_id: str) -> UploadHistory | None:
        return self._db.scalar(
            select(UploadHistory).where(UploadHistory.document_id == document_id)
        )
