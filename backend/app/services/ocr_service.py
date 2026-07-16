"""
OCRService — turn a document's pages into raw text; nothing more.

Second stage of the Phase 7 pipeline. Its single responsibility (requirement
4) is producing an OCRResult — raw text per page — using whichever route is
cheapest and most accurate per page:

    page has an embedded text layer -> take it verbatim (exact, confidence 1.0)
    page is pixels                  -> rasterize (PDFs) and run the OCRProvider

The service performs NO extraction, NO validation, and NO interpretation of
the text; that is the ExtractionEngine's job. Raw OCR output never leaves the
backend — routes only ever expose statistics about it.
"""

import logging

from app.core.config import Settings, settings
from app.core.exceptions import OCRFailedError
from app.domain.enums import DocumentCategory, DocumentQuality, ExtractionSource
from app.domain.extraction import DocumentAnalysis, OCRPage, OCRResult
from app.domain.repositories import DocumentInspector, OCRProvider

logger = logging.getLogger(__name__)


class OCRService:
    """Produce the raw text reading of one analyzed document."""

    def __init__(
        self,
        provider: OCRProvider,
        inspector: DocumentInspector,
        config: Settings = settings,
    ) -> None:
        self._provider = provider
        self._inspector = inspector
        self._render_dpi = config.OCR_RENDER_DPI

    def read_document(self, analysis: DocumentAnalysis, content: bytes) -> OCRResult:
        """
        Read every page of the document, guided by the analysis verdict.

        Per-page problems (blank page, an OCR pass that reads nothing, a
        single-page engine hiccup) become warnings on the result — the method
        only raises OCRFailedError if EVERY pixel page fails at the engine
        level, i.e. OCR is genuinely unavailable.
        """
        pages: list[OCRPage] = []
        warnings: list[str] = []
        engine_failures = 0
        ocr_pages_attempted = 0

        for page in analysis.pages:
            if page.has_text_layer:
                # Digital text — exact by definition, no OCR cost.
                text = self._inspector.pdf_page_text(content, page.page_number)
                pages.append(
                    OCRPage(
                        page_number=page.page_number,
                        text=text,
                        confidence=1.0,
                        source=ExtractionSource.PDF_TEXT_LAYER,
                        word_count=len(text.split()),
                    )
                )
                continue

            if page.quality == DocumentQuality.BLANK:
                # Analysis already ruled the page blank — don't waste an OCR
                # pass; record an empty page so page numbering stays intact.
                pages.append(self._empty_page(page.page_number))
                warnings.append(f"Page {page.page_number} is blank — skipped OCR.")
                continue

            ocr_pages_attempted += 1
            try:
                image_bytes = (
                    self._inspector.render_pdf_page(content, page.page_number, self._render_dpi)
                    if analysis.category == DocumentCategory.PDF
                    else content
                )
                recognized = self._provider.recognize(image_bytes)
            except OCRFailedError as exc:
                # Engine-level failure on this page: degrade to an empty page,
                # keep going — other pages may still succeed.
                engine_failures += 1
                pages.append(self._empty_page(page.page_number))
                warnings.append(f"OCR failed on page {page.page_number}: {exc.message}")
                continue

            if recognized.word_count == 0:
                warnings.append(f"Page {page.page_number} produced no readable text.")
            if recognized.rotation_applied:
                warnings.append(
                    f"Page {page.page_number} was rotated {recognized.rotation_applied}° "
                    "and auto-corrected before OCR."
                )
            pages.append(
                OCRPage(
                    page_number=page.page_number,
                    text=recognized.text,
                    confidence=recognized.confidence,
                    source=ExtractionSource.OCR,
                    word_count=recognized.word_count,
                )
            )

        if ocr_pages_attempted > 0 and engine_failures == ocr_pages_attempted:
            # Every page that NEEDED the engine hit an engine failure — that's
            # an OCR outage, not a document problem.
            raise OCRFailedError("the OCR engine failed on every page of the document.")

        non_empty = [p for p in pages if p.word_count > 0]
        mean_confidence = (
            round(sum(p.confidence for p in non_empty) / len(non_empty), 4)
            if non_empty
            else 0.0
        )
        result = OCRResult(
            document_id=analysis.document_id,
            engine=self._provider.engine_name(),
            pages=tuple(pages),
            mean_confidence=mean_confidence,
            warnings=tuple(warnings),
        )
        logger.info(
            "OCR complete for %s: %d pages, %d chars, mean confidence %.2f",
            analysis.document_id, len(pages), result.total_chars, mean_confidence,
        )
        return result

    def _empty_page(self, page_number: int) -> OCRPage:
        """A placeholder page for blank/failed pages (keeps numbering stable)."""
        return OCRPage(
            page_number=page_number,
            text="",
            confidence=0.0,
            source=ExtractionSource.OCR,
            word_count=0,
        )
