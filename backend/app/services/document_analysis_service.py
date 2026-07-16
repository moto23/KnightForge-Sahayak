"""
DocumentAnalysisService — structural understanding BEFORE any OCR runs.

First stage of the Phase 7 pipeline. Given an uploaded document's bytes and
metadata, it answers four questions (requirement 3):

    * what TYPE is this?      digital_pdf / scanned_pdf / mixed_pdf / image
    * how many PAGES?         PDF page count, or 1 for images
    * PDF or IMAGE?           taken from the Phase 6 category, verified here
    * how GOOD is the scan?   good / fair / poor / blank, per page + overall

All raw facts (page sizes, text-layer chars, pixel statistics) come from the
DocumentInspector port; this service only applies judgement, so it contains
zero PDF/imaging library code and is unit-testable with a fake inspector.
"""

import logging

from app.core.config import Settings, settings
from app.core.exceptions import DocumentUnreadableError
from app.domain.document import UploadedDocument
from app.domain.enums import DocumentCategory, DocumentQuality
from app.domain.extraction import DocumentAnalysis, ImageFacts, PageAnalysis
from app.domain.repositories import DocumentInspector

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Quality thresholds — tuned for Tesseract's practical limits.
# --------------------------------------------------------------------------- #

# Images below this pixel count on their short edge rarely OCR well.
_MIN_GOOD_EDGE_PX = 1000
_MIN_FAIR_EDGE_PX = 600

# Grayscale std-dev bands: near-zero means a blank page; low means faint text.
_BLANK_CONTRAST = 5.0
_POOR_CONTRAST = 25.0
_FAIR_CONTRAST = 45.0

_QUALITY_ORDER = {
    DocumentQuality.GOOD: 0,
    DocumentQuality.FAIR: 1,
    DocumentQuality.POOR: 2,
    DocumentQuality.BLANK: 3,
}


class DocumentAnalysisService:
    """Detect document type, page count, and quality for one uploaded document."""

    def __init__(self, inspector: DocumentInspector, config: Settings = settings) -> None:
        self._inspector = inspector
        self._min_text_chars = config.PDF_TEXT_LAYER_MIN_CHARS

    def analyze(self, document: UploadedDocument, content: bytes) -> DocumentAnalysis:
        """
        Produce the full structural verdict for a document.

        Raises DocumentUnreadableError (422) only when the bytes cannot be
        parsed at all — blank or poor pages are reported as warnings, never
        as errors (graceful handling, requirement 11).
        """
        if document.category == DocumentCategory.PDF:
            analysis = self._analyze_pdf(document, content)
        else:
            analysis = self._analyze_image(document, content)
        logger.info(
            "Analyzed %s: type=%s pages=%d quality=%s ocr_required=%s",
            document.document_id,
            analysis.document_type,
            analysis.page_count,
            analysis.overall_quality,
            analysis.ocr_required,
        )
        return analysis

    # ------------------------------------------------------------------ PDFs

    def _analyze_pdf(self, document: UploadedDocument, content: bytes) -> DocumentAnalysis:
        try:
            facts = self._inspector.pdf_page_facts(content)
        except ValueError as exc:
            raise DocumentUnreadableError(document.document_id, str(exc)) from exc
        if not facts:
            raise DocumentUnreadableError(document.document_id, "PDF contains no pages.")

        pages: list[PageAnalysis] = []
        warnings: list[str] = []
        for fact in facts:
            has_text = fact.text_chars >= self._min_text_chars
            if has_text:
                # An embedded text layer means exact text — quality is GOOD by
                # definition; pixels are irrelevant.
                quality = DocumentQuality.GOOD
            else:
                # No text layer: judge the page by its rendered pixels, the
                # same way we judge a standalone image (low DPI is fine here —
                # we only need statistics, not OCR accuracy).
                image_bytes = self._inspector.render_pdf_page(content, fact.page_number, dpi=72)
                quality = self._pixel_quality(self._inspector.image_facts(image_bytes))
                if quality == DocumentQuality.BLANK:
                    warnings.append(f"Page {fact.page_number} appears blank.")
                elif quality == DocumentQuality.POOR:
                    warnings.append(
                        f"Page {fact.page_number} is a poor-quality scan — OCR may be unreliable."
                    )
            pages.append(
                PageAnalysis(
                    page_number=fact.page_number,
                    width=fact.width,
                    height=fact.height,
                    has_text_layer=has_text,
                    text_chars=fact.text_chars,
                    quality=quality,
                )
            )

        with_text = sum(1 for p in pages if p.has_text_layer)
        if with_text == len(pages):
            document_type = "digital_pdf"
        elif with_text == 0:
            document_type = "scanned_pdf"
        else:
            document_type = "mixed_pdf"

        return DocumentAnalysis(
            document_id=document.document_id,
            category=DocumentCategory.PDF,
            document_type=document_type,
            page_count=len(pages),
            pages=tuple(pages),
            overall_quality=self._overall_quality(pages),
            ocr_required=with_text < len(pages),
            warnings=tuple(warnings),
        )

    # ---------------------------------------------------------------- images

    def _analyze_image(self, document: UploadedDocument, content: bytes) -> DocumentAnalysis:
        try:
            facts = self._inspector.image_facts(content)
        except ValueError as exc:
            raise DocumentUnreadableError(document.document_id, str(exc)) from exc

        quality = self._pixel_quality(facts)
        warnings: list[str] = []
        if quality == DocumentQuality.BLANK:
            warnings.append("The image appears blank.")
        elif quality == DocumentQuality.POOR:
            warnings.append("The image is low quality — OCR may be unreliable.")
        elif quality == DocumentQuality.FAIR:
            warnings.append("The image quality is only fair; some fields may be misread.")

        page = PageAnalysis(
            page_number=1,
            width=facts.width,
            height=facts.height,
            has_text_layer=False,  # pixels never carry embedded text
            text_chars=0,
            quality=quality,
        )
        return DocumentAnalysis(
            document_id=document.document_id,
            category=DocumentCategory.IMAGE,
            document_type="image",
            page_count=1,
            pages=(page,),
            overall_quality=quality,
            ocr_required=True,
            warnings=tuple(warnings),
        )

    # ------------------------------------------------------------- judgement

    def _pixel_quality(self, facts: ImageFacts) -> DocumentQuality:
        """
        Grade legibility from pixel statistics.

        Contrast (grayscale std-dev) separates blank/faint/crisp; resolution
        caps the grade because tiny images can't OCR well no matter how sharp.
        """
        if facts.contrast < _BLANK_CONTRAST:
            return DocumentQuality.BLANK

        if facts.contrast < _POOR_CONTRAST:
            by_contrast = DocumentQuality.POOR
        elif facts.contrast < _FAIR_CONTRAST:
            by_contrast = DocumentQuality.FAIR
        else:
            by_contrast = DocumentQuality.GOOD

        short_edge = min(facts.width, facts.height)
        if short_edge < _MIN_FAIR_EDGE_PX:
            by_resolution = DocumentQuality.POOR
        elif short_edge < _MIN_GOOD_EDGE_PX:
            by_resolution = DocumentQuality.FAIR
        else:
            by_resolution = DocumentQuality.GOOD

        # The worse of the two verdicts wins.
        return max(by_contrast, by_resolution, key=lambda q: _QUALITY_ORDER[q])

    def _overall_quality(self, pages: list[PageAnalysis]) -> DocumentQuality:
        """Worst NON-BLANK page decides; all-blank documents are blank overall."""
        non_blank = [p.quality for p in pages if p.quality != DocumentQuality.BLANK]
        if not non_blank:
            return DocumentQuality.BLANK
        return max(non_blank, key=lambda q: _QUALITY_ORDER[q])
