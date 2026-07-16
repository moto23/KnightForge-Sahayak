"""
PyMuPdfInspector — the DocumentInspector port implemented with PyMuPDF + Pillow.

Confines all PDF parsing and pixel work to infrastructure, mirroring the
Tesseract rule: no module outside `app/infrastructure/ocr/` imports fitz or
PIL. The adapter reports raw FACTS (page sizes, text-layer character counts,
pixel statistics); the DocumentAnalysisService turns facts into judgements
(digital vs scanned, good vs poor quality).
"""

import io
import logging

import fitz  # PyMuPDF
from PIL import Image, ImageStat

from app.domain.extraction import ImageFacts, PdfPageFacts
from app.domain.repositories import DocumentInspector

logger = logging.getLogger(__name__)


class PyMuPdfInspector(DocumentInspector):
    """DocumentInspector adapter over PyMuPDF (PDFs) and Pillow (images)."""

    # ------------------------------------------------------------------ PDFs

    def pdf_page_facts(self, pdf_bytes: bytes) -> tuple[PdfPageFacts, ...]:
        """Open the PDF once and report size + text-layer stats per page."""
        with self._open(pdf_bytes) as doc:
            facts = []
            for index, page in enumerate(doc, start=1):
                text = page.get_text().strip()
                facts.append(
                    PdfPageFacts(
                        page_number=index,
                        width=int(page.rect.width),
                        height=int(page.rect.height),
                        text_chars=len(text),
                    )
                )
            return tuple(facts)

    def pdf_page_text(self, pdf_bytes: bytes, page_number: int) -> str:
        """Extract one page's embedded text layer (empty string if none)."""
        with self._open(pdf_bytes) as doc:
            return doc[page_number - 1].get_text().strip()

    def render_pdf_page(self, pdf_bytes: bytes, page_number: int, dpi: int) -> bytes:
        """Rasterize one page to PNG bytes at the requested DPI (for OCR)."""
        with self._open(pdf_bytes) as doc:
            pixmap = doc[page_number - 1].get_pixmap(dpi=dpi)
            return pixmap.tobytes("png")

    # ---------------------------------------------------------------- images

    def image_facts(self, image_bytes: bytes) -> ImageFacts:
        """
        Decode an image and compute legibility statistics on its grayscale
        version: std-dev (contrast) and mean (brightness).
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image.load()
        except Exception as exc:
            raise ValueError(f"image could not be decoded: {exc}") from exc

        gray = image.convert("L")
        stat = ImageStat.Stat(gray)
        return ImageFacts(
            width=image.width,
            height=image.height,
            contrast=round(stat.stddev[0], 2),
            brightness=round(stat.mean[0], 2),
        )

    # -------------------------------------------------------------- internals

    def _open(self, pdf_bytes: bytes) -> fitz.Document:
        """Open PDF bytes; normalize parser errors to ValueError for the domain."""
        try:
            return fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"PDF could not be parsed: {exc}") from exc
