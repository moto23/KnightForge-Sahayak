"""
Document-understanding domain models (Phase 7).

Every stage of the Intelligent Document Understanding Pipeline speaks in these
frozen, strongly-typed models:

    DocumentAnalysis   — what the document IS (type, pages, quality)
    RecognizedText     — what the OCR engine READ from one image (raw)
    OCRResult          — the full raw text of a document, page by page
    ExtractedField     — one KYC field's value, scored and validated
    ExtractionResult   — the complete structured output of extraction
    PrefillReport      — what was (and wasn't) auto-filled into a session

Raw OCR text lives ONLY inside RecognizedText / OCRResult and never crosses
the API boundary — clients always receive the structured ExtractionResult.
Like the rest of the domain, this module has no I/O and no framework imports.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    DocumentCategory,
    DocumentQuality,
    ExtractionMethod,
    ExtractionSource,
)
from app.domain.session import utc_now
from app.domain.validators.result import ValidationResult


class PdfPageFacts(BaseModel):
    """
    Raw structural facts about one PDF page, as reported by the
    DocumentInspector port — no judgement applied (that's the
    DocumentAnalysisService's job).
    """

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(..., ge=1, description="1-based page index.")
    width: int = Field(..., description="Page width in PDF points.")
    height: int = Field(..., description="Page height in PDF points.")
    text_chars: int = Field(..., description="Characters in the embedded text layer.")


class ImageFacts(BaseModel):
    """
    Raw pixel statistics of one image, as reported by the DocumentInspector.

    `contrast` is the standard deviation of grayscale pixel values (0-128
    realistic range): a blank page is near 0, a crisp document scan is high.
    """

    model_config = ConfigDict(frozen=True)

    width: int = Field(..., description="Image width in pixels.")
    height: int = Field(..., description="Image height in pixels.")
    contrast: float = Field(..., description="Grayscale std-dev — proxy for legibility.")
    brightness: float = Field(..., description="Mean grayscale value (0-255).")


class PageAnalysis(BaseModel):
    """Structural facts about one page of an uploaded document."""

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(..., ge=1, description="1-based page index.")
    width: int = Field(..., description="Page/image width in pixels or PDF points.")
    height: int = Field(..., description="Page/image height in pixels or PDF points.")
    has_text_layer: bool = Field(
        ..., description="True if the page carries usable embedded (digital) text."
    )
    text_chars: int = Field(
        default=0, description="Number of characters in the embedded text layer."
    )
    quality: DocumentQuality = Field(..., description="Estimated scan quality of this page.")


class DocumentAnalysis(BaseModel):
    """
    The DocumentAnalysisService verdict: what kind of document this is and
    what the pipeline should expect from it (produced BEFORE any OCR runs).
    """

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(..., description="Id of the analyzed uploaded document.")
    category: DocumentCategory = Field(..., description="Storage category: pdf or image.")
    document_type: str = Field(
        ...,
        description=(
            "Detected structural type: 'digital_pdf' (embedded text on every "
            "page), 'scanned_pdf' (no usable text layer), 'mixed_pdf', or 'image'."
        ),
    )
    page_count: int = Field(..., ge=1, description="Number of pages (1 for images).")
    pages: tuple[PageAnalysis, ...] = Field(..., description="Per-page structural facts.")
    overall_quality: DocumentQuality = Field(
        ..., description="Worst non-blank page quality (blank if ALL pages are blank)."
    )
    ocr_required: bool = Field(
        ..., description="True if at least one page needs pixel OCR (no text layer)."
    )
    warnings: tuple[str, ...] = Field(
        default=(), description="Human-readable caveats (poor scan, blank page…)."
    )


class RecognizedText(BaseModel):
    """
    Raw output of ONE OCR pass over ONE image — exactly what the engine read.

    This is the OCRProvider port's return type: providers produce it, the
    OCRService aggregates it, and nothing beyond the ExtractionEngine ever
    consumes the `text` inside.
    """

    model_config = ConfigDict(frozen=True)

    text: str = Field(..., description="The raw recognized text (unmodified).")
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Mean word-level confidence reported by the engine (0-1).",
    )
    word_count: int = Field(default=0, description="Number of words recognized.")
    rotation_applied: int = Field(
        default=0,
        description="Degrees the image was auto-rotated before recognition (0/90/180/270).",
    )


class OCRPage(BaseModel):
    """Raw text of one document page, tagged with where it came from."""

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(..., ge=1, description="1-based page index.")
    text: str = Field(..., description="Raw page text (text layer or OCR). Internal only.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence of this page's text (0-1)."
    )
    source: ExtractionSource = Field(
        ..., description="pdf_text_layer (exact) or ocr (probabilistic)."
    )
    word_count: int = Field(default=0, description="Words on this page.")


class OCRResult(BaseModel):
    """
    The complete raw reading of one document — the OCRService's only output.

    Raw text stays server-side: API responses expose page counts, confidences,
    and character totals, never `pages[*].text` itself.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(..., description="Id of the document that was read.")
    engine: str = Field(..., description="Which engine produced the text (e.g. 'tesseract 5.4').")
    pages: tuple[OCRPage, ...] = Field(..., description="Raw text per page, in order.")
    mean_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence averaged over all non-empty pages."
    )
    warnings: tuple[str, ...] = Field(
        default=(), description="Per-page problems handled gracefully (blank page, OCR miss…)."
    )

    @property
    def full_text(self) -> str:
        """All pages joined — for internal extraction use only."""
        return "\n".join(page.text for page in self.pages)

    @property
    def total_chars(self) -> int:
        """Total characters recognized across the document."""
        return sum(len(page.text) for page in self.pages)


class ExtractedField(BaseModel):
    """
    One KYC field extracted from a document — the pipeline's atomic output.

    Carries everything requirement 6 demands: field_id, value, confidence,
    source, and the Validation Engine's verdict. `accepted` is the pipeline's
    final ruling: valid AND confident enough to be trusted for prefill.
    """

    model_config = ConfigDict(frozen=True)

    field_id: str = Field(..., description="KYC schema field id this value belongs to.")
    value: str = Field(..., description="The cleaned extracted value.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Final confidence after all scoring (0-1)."
    )
    source: ExtractionSource = Field(..., description="Where the text came from.")
    method: ExtractionMethod = Field(..., description="How the value was matched to the field.")
    page_number: int = Field(..., ge=1, description="Page the value was found on.")
    validation_result: ValidationResult = Field(
        ..., description="The deterministic Validation Engine's verdict on the value."
    )
    accepted: bool = Field(
        ...,
        description="True only if the value is VALID and confidence beats the prefill threshold.",
    )


class ExtractionResult(BaseModel):
    """The structured output of the whole understanding pipeline for one document."""

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(..., description="Id of the source document.")
    is_kyc_form: bool = Field(
        ..., description="True if the document looks like the CVL Individual KYC form."
    )
    fields: tuple[ExtractedField, ...] = Field(
        default=(), description="Every field the engine could extract, valid or not."
    )
    missing_required: tuple[str, ...] = Field(
        default=(), description="Required schema field ids NOT found in the document."
    )
    warnings: tuple[str, ...] = Field(
        default=(), description="Extraction-level caveats (partial extraction, low quality…)."
    )

    @property
    def accepted_fields(self) -> tuple[ExtractedField, ...]:
        """Only the fields that passed validation and the confidence bar."""
        return tuple(f for f in self.fields if f.accepted)

    @property
    def rejected_fields(self) -> tuple[ExtractedField, ...]:
        """Fields that were found but failed validation or scored too low."""
        return tuple(f for f in self.fields if not f.accepted)


class PrefilledField(BaseModel):
    """One field the SessionPrefillService wrote into an interview session."""

    model_config = ConfigDict(frozen=True)

    field_id: str = Field(..., description="KYC field id that was prefilled.")
    value: str = Field(..., description="The value stored in the session.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence.")


class SkippedField(BaseModel):
    """One extracted field the prefill deliberately did NOT write, and why."""

    model_config = ConfigDict(frozen=True)

    field_id: str = Field(..., description="KYC field id that was skipped.")
    reason: str = Field(
        ...,
        description=(
            "Machine-readable skip reason: 'low_confidence', 'invalid_value', "
            "or 'already_answered'."
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence.")


class PrefillReport(BaseModel):
    """Everything that happened during one automatic session prefill."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(..., description="The interview session that was updated.")
    document_id: str = Field(..., description="The document the values came from.")
    prefilled: tuple[PrefilledField, ...] = Field(
        default=(), description="Fields written into the session (high-confidence + valid only)."
    )
    skipped: tuple[SkippedField, ...] = Field(
        default=(), description="Extracted fields deliberately left for the interview."
    )
    remaining_required: tuple[str, ...] = Field(
        default=(), description="Required field ids still unanswered after prefill."
    )
    progress_percentage: float = Field(
        ..., description="Session progress after prefill (0-100)."
    )


class DocumentUnderstanding(BaseModel):
    """
    The cached record of one document's trip through the pipeline —
    analysis + raw OCR + structured extraction, stamped with when it ran.
    Stored via the DocumentUnderstandingRepository so GET /ocr/{document_id}
    and POST /ocr/prefill can reuse results instead of re-running OCR.
    """

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(..., description="Id of the understood document.")
    analysis: DocumentAnalysis = Field(..., description="Structural analysis verdict.")
    ocr: OCRResult = Field(..., description="Raw OCR reading (never exposed to clients).")
    extraction: ExtractionResult = Field(..., description="Structured extraction output.")
    processed_at: datetime = Field(
        default_factory=utc_now, description="When the pipeline ran (UTC)."
    )
