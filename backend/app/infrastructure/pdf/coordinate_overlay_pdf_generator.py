"""
CoordinateOverlayPDFGenerator — the PDFGenerator port implemented with PyMuPDF.

The ONLY module that uses a PDF library for WRITING. It opens the original
template, paints each Placement (text at a baseline, or a vector checkmark
inside a checkbox), and returns the merged bytes. The template's own content
stream is untouched — layout, fonts, and spacing are preserved exactly;
user data is drawn on top (requirement 11).

Coordinate convention: Placements arrive in TOP-LEFT-origin PDF points, which
is also PyMuPDF's native page coordinate system — no Y-flip needed. (If this
adapter were rebuilt on ReportLab, whose origin is bottom-left, the flip would
happen HERE, invisible to the service layer.)
"""

import logging

import fitz  # PyMuPDF

from app.domain.pdf import OverlayPlan, Placement
from app.domain.repositories import PDFGenerator

logger = logging.getLogger(__name__)

# Overlay ink: a dark blue that reads as "filled by hand with a pen" and is
# visually distinct from the template's black print.
_INK = (0.05, 0.05, 0.45)

# Checkmark stroke half-size in points (fits the form's 6.5 pt boxes).
_CHECK_HALF = 2.6


class CoordinateOverlayPDFGenerator(PDFGenerator):
    """PDFGenerator adapter that stamps an OverlayPlan onto a template."""

    def engine_name(self) -> str:
        """Renderer identifier for logs."""
        return f"pymupdf {fitz.__version__}"

    def page_count(self, pdf_bytes: bytes) -> int:
        """Page count of a finished PDF (for metadata)."""
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return doc.page_count

    def render(self, template_bytes: bytes, plan: OverlayPlan) -> bytes:
        """
        Merge the plan onto the template; return final PDF bytes.

        Raises ValueError for an unopenable/corrupt template and RuntimeError
        for rendering failures — the service maps both to typed DomainErrors.
        """
        try:
            doc = fitz.open(stream=template_bytes, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"template could not be opened: {exc}") from exc

        try:
            for placement in plan.placements:
                if placement.page > doc.page_count:
                    logger.warning(
                        "Placement for %s targets page %d but template has %d — skipped",
                        placement.field_id, placement.page, doc.page_count,
                    )
                    continue
                page = doc[placement.page - 1]
                if placement.kind == "checkmark":
                    self._draw_checkmark(page, placement)
                elif placement.text:  # empty text = deliberate no-op (boolean 'no')
                    self._draw_text(page, placement)
            return doc.tobytes()
        except Exception as exc:
            raise RuntimeError(f"overlay rendering failed: {exc}") from exc
        finally:
            doc.close()

    # ------------------------------------------------------------------ #
    # Primitives
    # ------------------------------------------------------------------ #

    def _draw_text(self, page: fitz.Page, placement: Placement) -> None:
        """
        Draw a string with its BASELINE at (x, y), shrinking the font just
        enough to respect max_width so long values never spill over the form.
        """
        font = fitz.Font("helv")
        size = placement.font_size
        if placement.max_width:
            width = font.text_length(placement.text, fontsize=size)
            if width > placement.max_width:
                size = max(5.0, size * placement.max_width / width)
        page.insert_text(
            fitz.Point(placement.x, placement.y),
            placement.text,
            fontsize=size,
            fontname="helv",
            color=_INK,
        )

    def _draw_checkmark(self, page: fitz.Page, placement: Placement) -> None:
        """Draw a ✓ as two strokes centered on the checkbox at (x, y)."""
        cx, cy, h = placement.x, placement.y, _CHECK_HALF
        page.draw_line(
            fitz.Point(cx - h, cy), fitz.Point(cx - h * 0.2, cy + h * 0.9),
            color=_INK, width=1.1,
        )
        page.draw_line(
            fitz.Point(cx - h * 0.2, cy + h * 0.9), fitz.Point(cx + h * 1.1, cy - h),
            color=_INK, width=1.1,
        )
