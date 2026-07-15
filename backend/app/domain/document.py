"""
Uploaded-document domain model (Phase 6).

`UploadedDocument` is the metadata record the upload pipeline produces: the
system-generated identity of a file plus everything later phases (OCR, audit)
need to find and reason about it. It is frozen — once a file is stored its
record never mutates; delete-and-reupload is the only "edit".

The user-supplied original filename is kept ONLY as display metadata. It is
never used to name, locate, or open anything on disk — the stored filename is
always `<uuid><normalized extension>`, generated server-side.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DocumentCategory
from app.domain.session import utc_now


class UploadedDocument(BaseModel):
    """Immutable metadata for one stored upload."""

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(..., description="Server-generated UUID identifying the document.")
    original_filename: str = Field(
        ..., description="Client-supplied filename — display metadata only, never trusted."
    )
    stored_filename: str = Field(
        ..., description="Server-generated on-disk name: <document_id><extension>."
    )
    content_type: str = Field(..., description="Validated MIME type of the file.")
    file_size: int = Field(..., ge=1, description="File size in bytes.")
    category: DocumentCategory = Field(
        ..., description="Storage category (pdf/image) deciding the subdirectory."
    )
    uploaded_at: datetime = Field(
        default_factory=utc_now, description="When the upload completed (UTC)."
    )
