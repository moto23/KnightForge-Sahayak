"""
PDF-generation domain models (Phase 8).

Vocabulary shared by the coordinate mapper, the PDF port, and the generation
service:

    Placement      — one primitive mark (text or checkmark) at (page, x, y)
    OverlayPlan    — every Placement for one session, ready to render
    GeneratedPdf   — metadata record of one produced PDF file

Placements use PDF-point coordinates with a TOP-LEFT origin (y grows downward,
matching how the template was measured); the infrastructure adapter converts
to its library's native origin. Session.answers is the only data source that
ever becomes an OverlayPlan — OCR results never reach this module.

Pure domain: no I/O, no framework imports.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import PlacementKind
from app.domain.session import utc_now


class Placement(BaseModel):
    """One primitive mark the overlay must paint onto the template."""

    model_config = ConfigDict(frozen=True)

    kind: PlacementKind = Field(..., description="text or checkmark.")
    page: int = Field(..., ge=1, description="1-based template page number.")
    x: float = Field(..., description="X in PDF points from the LEFT edge.")
    y: float = Field(..., description="Y in PDF points from the TOP edge.")
    text: str = Field(default="", description="The string to draw (TEXT only).")
    font_size: float = Field(default=8.0, description="Font size in points (TEXT only).")
    max_width: float | None = Field(
        default=None,
        description="Optional width budget in points; renderer shrinks text to fit.",
    )
    field_id: str = Field(..., description="KYC field this mark belongs to (for logs).")


class OverlayPlan(BaseModel):
    """
    The complete, schema-free drawing plan for one session's PDF.

    Produced by the CoordinateMapper from Session.answers; consumed by the
    PDFGenerator port. Adapters iterate placements — they never see field
    types, options, or the KYC schema.
    """

    model_config = ConfigDict(frozen=True)

    template_id: str = Field(..., description="Which coordinate map produced this plan.")
    template_version: str = Field(..., description="Version of the coordinate map used.")
    placements: tuple[Placement, ...] = Field(..., description="Every mark to paint.")
    unmapped_fields: tuple[str, ...] = Field(
        default=(),
        description="Answered field ids that have no coordinate entry (reported, not fatal).",
    )


class GeneratedPdf(BaseModel):
    """Metadata record of one generated PDF (requirement 8)."""

    model_config = ConfigDict(frozen=True)

    pdf_id: str = Field(..., description="Server-generated UUID of this PDF.")
    stored_filename: str = Field(..., description="On-disk name: <pdf_id>.pdf.")
    generated_by_session: str = Field(..., description="Session whose answers filled the form.")
    template_id: str = Field(..., description="Template/coordinate-map id used.")
    template_version: str = Field(..., description="Coordinate-map version used.")
    page_count: int = Field(..., ge=1, description="Pages in the generated PDF.")
    file_size: int = Field(..., ge=1, description="Size of the file in bytes.")
    fields_filled: int = Field(..., ge=0, description="Answered fields painted onto the form.")
    generated_at: datetime = Field(
        default_factory=utc_now, description="When the PDF was produced (UTC)."
    )
