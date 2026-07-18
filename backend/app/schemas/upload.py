"""
Pydantic request/response DTOs for the /upload endpoints (Phase 6).

Every endpoint returns one of these typed models — never a raw dict — so the
OpenAPI schema is complete and the frontend gets a stable contract.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.document import UploadedDocument
from app.domain.enums import DocumentCategory
from app.infrastructure.db.models import UploadHistory


class DocumentMetadataResponse(BaseModel):
    """Public metadata for one uploaded document."""

    document_id: str = Field(..., description="Server-generated UUID of the document.")
    original_filename: str = Field(..., description="Filename as uploaded (display only).")
    stored_filename: str = Field(..., description="Server-generated on-disk filename.")
    content_type: str = Field(..., description="Validated MIME type.")
    file_size: int = Field(..., description="Size in bytes.")
    category: DocumentCategory = Field(..., description="Storage category (pdf/image).")
    uploaded_at: datetime = Field(..., description="Upload timestamp (UTC).")

    @classmethod
    def from_document(cls, document: UploadedDocument) -> "DocumentMetadataResponse":
        """Map the domain record onto the API DTO."""
        return cls(**document.model_dump())


class UploadResponse(BaseModel):
    """Returned by POST /upload after a successful upload."""

    message: str = Field(..., description="Human-readable confirmation.")
    document: DocumentMetadataResponse = Field(..., description="Stored document metadata.")


class ListUploadsResponse(BaseModel):
    """Returned by GET /upload — every stored document, newest first."""

    total: int = Field(..., description="Number of stored documents.")
    documents: list[DocumentMetadataResponse] = Field(
        default_factory=list, description="Metadata records, newest upload first."
    )


class DeleteUploadResponse(BaseModel):
    """Returned by DELETE /upload/{document_id}."""

    document_id: str = Field(..., description="Id of the deleted document.")
    deleted: bool = Field(..., description="True — the document and its file were removed.")


class UploadHistoryItemResponse(BaseModel):
    """One persistent upload-history row (Phase 13)."""

    history_id: str = Field(..., description="Row id.")
    document_id: str = Field(..., description="Uploaded document's UUID.")
    filename: str = Field(..., description="Original filename (display only).")
    document_type: str = Field(..., description="User-selected type slug (e.g. pan_card).")
    detected_type: str | None = Field(None, description="AI-detected type label, once known.")
    file_size: int = Field(..., description="Size in bytes.")
    ocr_status: str = Field(..., description="pending | completed | failed.")
    processing_status: str = Field(..., description="uploaded | analyzed | prefilled | deleted.")
    uploaded_at: datetime = Field(..., description="Upload timestamp (UTC).")

    @classmethod
    def from_row(cls, row: UploadHistory) -> "UploadHistoryItemResponse":
        """Map the ORM row onto the API DTO."""
        return cls(
            history_id=row.id,
            document_id=row.document_id,
            filename=row.filename,
            document_type=row.document_type,
            detected_type=row.detected_type,
            file_size=row.file_size,
            ocr_status=row.ocr_status,
            processing_status=row.processing_status,
            uploaded_at=row.uploaded_at,
        )


class UploadHistoryResponse(BaseModel):
    """Returned by GET /upload/history — the caller's uploads, newest first."""

    total: int = Field(..., description="Number of history rows returned.")
    items: list[UploadHistoryItemResponse] = Field(default_factory=list)
