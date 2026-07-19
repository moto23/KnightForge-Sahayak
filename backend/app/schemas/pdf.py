"""
Pydantic request/response DTOs for the /pdf endpoints (Phase 8).

Typed contracts only — no raw dicts. The download endpoint itself returns the
binary file via FileResponse; these models cover generation and metadata.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.pdf import GeneratedPdf


class GeneratePdfRequest(BaseModel):
    """Body of POST /pdf/generate."""

    session_id: str = Field(
        ..., description="Completed interview session whose answers fill the form."
    )


class GeneratedPdfResponse(BaseModel):
    """Metadata + download info for one generated PDF (requirement 8)."""

    pdf_id: str = Field(..., description="Server-generated UUID of the PDF.")
    generated_by_session: str = Field(..., description="Source session id.")
    template_id: str = Field(..., description="Template the form was filled onto.")
    template_version: str = Field(..., description="Coordinate-map version used.")
    page_count: int = Field(..., description="Pages in the generated PDF.")
    file_size: int = Field(..., description="File size in bytes.")
    fields_filled: int = Field(..., description="Answered fields painted onto the form.")
    generated_at: datetime = Field(..., description="Generation time (UTC).")
    download_url: str = Field(..., description="Relative URL to download the file.")
    is_current: bool = Field(
        default=False,
        description=(
            "True when this PDF was generated from the session's CURRENT "
            "answers. False means the workflow moved on (a document was "
            "deleted, an answer changed) — the file is history, not the "
            "current output. The file itself is never modified."
        ),
    )

    @classmethod
    def from_domain(
        cls, record: GeneratedPdf, current_fingerprint: str | None = None
    ) -> "GeneratedPdfResponse":
        """
        Map the domain record onto the API DTO (adds the download URL).

        `current_fingerprint` is the live session's answer digest; when it is
        supplied the DTO reports whether this PDF still matches it.
        """
        return cls(
            pdf_id=record.pdf_id,
            generated_by_session=record.generated_by_session,
            template_id=record.template_id,
            template_version=record.template_version,
            page_count=record.page_count,
            file_size=record.file_size,
            fields_filled=record.fields_filled,
            generated_at=record.generated_at,
            download_url=f"/pdf/{record.pdf_id}/download",
            is_current=(
                current_fingerprint is not None
                and record.answers_fingerprint == current_fingerprint
            ),
        )


class GeneratePdfResponse(BaseModel):
    """Returned by POST /pdf/generate."""

    message: str = Field(..., description="Human-readable confirmation.")
    pdf: GeneratedPdfResponse = Field(..., description="The generated PDF's metadata.")


class DeletePdfResponse(BaseModel):
    """Returned by DELETE /pdf/{pdf_id}."""

    pdf_id: str = Field(..., description="Id of the deleted PDF.")
    deleted: bool = Field(..., description="True — file and metadata removed.")
