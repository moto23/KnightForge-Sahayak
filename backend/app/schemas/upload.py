"""
Pydantic request/response DTOs for the /upload endpoints (Phase 6).

Every endpoint returns one of these typed models — never a raw dict — so the
OpenAPI schema is complete and the frontend gets a stable contract.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.document import UploadedDocument
from app.domain.enums import DocumentCategory


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
