"""
Pydantic request/response DTOs for the /ocr endpoints (Phase 7).

The DTOs enforce the phase's core privacy rule: RAW OCR TEXT NEVER LEAVES THE
BACKEND. OCRRunResponse exposes statistics (pages, confidence, character
counts) — not `text`. Clients only ever receive the STRUCTURED extraction:
field_id / value / confidence / source / validation_result.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import (
    DocumentCategory,
    DocumentQuality,
    ExtractionMethod,
    ExtractionSource,
)
from app.domain.extraction import (
    DocumentAnalysis,
    DocumentUnderstanding,
    ExtractionResult,
    OCRResult,
    PrefillReport,
)

# --------------------------------------------------------------------------- #
# Shared building blocks
# --------------------------------------------------------------------------- #


class PageAnalysisResponse(BaseModel):
    """Structural facts about one document page."""

    page_number: int = Field(..., description="1-based page index.")
    width: int = Field(..., description="Width in pixels (image) or PDF points.")
    height: int = Field(..., description="Height in pixels (image) or PDF points.")
    has_text_layer: bool = Field(..., description="True if the page has embedded digital text.")
    quality: DocumentQuality = Field(..., description="Estimated scan quality.")


class DocumentAnalysisResponse(BaseModel):
    """The document-detection verdict (type, pages, quality)."""

    document_id: str = Field(..., description="Id of the analyzed document.")
    category: DocumentCategory = Field(..., description="pdf or image.")
    document_type: str = Field(
        ..., description="digital_pdf | scanned_pdf | mixed_pdf | image."
    )
    page_count: int = Field(..., description="Number of pages (1 for images).")
    overall_quality: DocumentQuality = Field(..., description="good | fair | poor | blank.")
    ocr_required: bool = Field(..., description="True if pixel OCR was needed.")
    pages: list[PageAnalysisResponse] = Field(..., description="Per-page facts.")
    warnings: list[str] = Field(default_factory=list, description="Quality caveats.")

    @classmethod
    def from_domain(cls, analysis: DocumentAnalysis) -> "DocumentAnalysisResponse":
        """Map the domain analysis onto the API DTO."""
        return cls(
            document_id=analysis.document_id,
            category=analysis.category,
            document_type=analysis.document_type,
            page_count=analysis.page_count,
            overall_quality=analysis.overall_quality,
            ocr_required=analysis.ocr_required,
            pages=[
                PageAnalysisResponse(
                    page_number=p.page_number,
                    width=p.width,
                    height=p.height,
                    has_text_layer=p.has_text_layer,
                    quality=p.quality,
                )
                for p in analysis.pages
            ],
            warnings=list(analysis.warnings),
        )


class OCRSummaryResponse(BaseModel):
    """
    Statistics about the raw OCR pass — deliberately WITHOUT the text itself
    (raw OCR output is internal; clients get structured extraction only).
    """

    engine: str = Field(..., description="OCR engine that produced the reading.")
    pages_read: int = Field(..., description="Pages processed (text layer or OCR).")
    total_chars: int = Field(..., description="Total characters recognized.")
    mean_confidence: float = Field(..., description="Mean page confidence (0-1).")
    warnings: list[str] = Field(default_factory=list, description="Per-page issues handled.")

    @classmethod
    def from_domain(cls, ocr: OCRResult) -> "OCRSummaryResponse":
        """Summarize the raw OCR result without exposing text."""
        return cls(
            engine=ocr.engine,
            pages_read=len(ocr.pages),
            total_chars=ocr.total_chars,
            mean_confidence=ocr.mean_confidence,
            warnings=list(ocr.warnings),
        )


class ValidationVerdict(BaseModel):
    """The deterministic Validation Engine's ruling on one extracted value."""

    valid: bool = Field(..., description="True if the value passed all rules.")
    code: str = Field(..., description="Machine-readable result code.")
    message: str = Field(..., description="Human-readable explanation.")


class ExtractedFieldResponse(BaseModel):
    """One structured KYC field pulled from the document (requirement 6)."""

    field_id: str = Field(..., description="KYC schema field id.")
    value: str = Field(..., description="The extracted value.")
    confidence: float = Field(..., description="Final confidence score (0-1).")
    source: ExtractionSource = Field(..., description="pdf_text_layer or ocr.")
    method: ExtractionMethod = Field(..., description="How the value was matched.")
    page_number: int = Field(..., description="Page it was found on.")
    validation_result: ValidationVerdict = Field(..., description="Validation Engine verdict.")
    accepted: bool = Field(
        ..., description="True if valid AND confident enough for automatic prefill."
    )


class ExtractionResponse(BaseModel):
    """The full structured extraction for one document."""

    document_id: str = Field(..., description="Source document id.")
    is_kyc_form: bool = Field(..., description="Whether it looks like the CVL KYC form.")
    fields_found: int = Field(..., description="Total fields extracted (valid or not).")
    fields_accepted: int = Field(..., description="Fields that cleared validation + confidence.")
    fields: list[ExtractedFieldResponse] = Field(..., description="Every extracted field.")
    missing_required: list[str] = Field(
        ..., description="Required schema fields NOT found in the document."
    )
    warnings: list[str] = Field(default_factory=list, description="Extraction caveats.")

    @classmethod
    def from_domain(cls, extraction: ExtractionResult) -> "ExtractionResponse":
        """Map the domain extraction onto the API DTO."""
        return cls(
            document_id=extraction.document_id,
            is_kyc_form=extraction.is_kyc_form,
            fields_found=len(extraction.fields),
            fields_accepted=len(extraction.accepted_fields),
            fields=[
                ExtractedFieldResponse(
                    field_id=f.field_id,
                    value=f.value,
                    confidence=f.confidence,
                    source=f.source,
                    method=f.method,
                    page_number=f.page_number,
                    validation_result=ValidationVerdict(
                        valid=f.validation_result.valid,
                        code=f.validation_result.code,
                        message=f.validation_result.message,
                    ),
                    accepted=f.accepted,
                )
                for f in extraction.fields
            ],
            missing_required=list(extraction.missing_required),
            warnings=list(extraction.warnings),
        )


# --------------------------------------------------------------------------- #
# Endpoint requests / responses
# --------------------------------------------------------------------------- #


class OCRProcessRequest(BaseModel):
    """Body of POST /ocr and POST /ocr/extract."""

    document_id: str = Field(..., description="Id of a previously uploaded document.")
    force: bool = Field(
        default=False,
        description="Re-run the pipeline even if a cached result exists.",
    )


class OCRRunResponse(BaseModel):
    """Returned by POST /ocr — analysis + OCR statistics (no raw text)."""

    document_id: str = Field(..., description="The processed document.")
    analysis: DocumentAnalysisResponse = Field(..., description="Document-detection verdict.")
    ocr: OCRSummaryResponse = Field(..., description="Raw-OCR statistics (text stays internal).")
    processed_at: datetime = Field(..., description="When the pipeline ran (UTC).")

    @classmethod
    def from_domain(cls, record: DocumentUnderstanding) -> "OCRRunResponse":
        return cls(
            document_id=record.document_id,
            analysis=DocumentAnalysisResponse.from_domain(record.analysis),
            ocr=OCRSummaryResponse.from_domain(record.ocr),
            processed_at=record.processed_at,
        )


class OCRExtractResponse(BaseModel):
    """Returned by POST /ocr/extract — the structured KYC extraction."""

    extraction: ExtractionResponse = Field(..., description="Structured KYC fields.")
    analysis: DocumentAnalysisResponse = Field(..., description="Document-detection verdict.")
    ocr: OCRSummaryResponse = Field(..., description="Raw-OCR statistics.")
    processed_at: datetime = Field(..., description="When the pipeline ran (UTC).")

    @classmethod
    def from_domain(cls, record: DocumentUnderstanding) -> "OCRExtractResponse":
        return cls(
            extraction=ExtractionResponse.from_domain(record.extraction),
            analysis=DocumentAnalysisResponse.from_domain(record.analysis),
            ocr=OCRSummaryResponse.from_domain(record.ocr),
            processed_at=record.processed_at,
        )


class PrefillRequest(BaseModel):
    """Body of POST /ocr/prefill."""

    document_id: str = Field(..., description="Document to take values from.")
    session_id: str = Field(..., description="Interview session to prefill.")
    overwrite: bool = Field(
        default=False,
        description="Overwrite answers the user already gave (default: never).",
    )


class PrefilledFieldResponse(BaseModel):
    """One field written into the session."""

    field_id: str = Field(..., description="KYC field id.")
    value: str = Field(..., description="Value stored in the session.")
    confidence: float = Field(..., description="Extraction confidence (0-1).")


class SkippedFieldResponse(BaseModel):
    """One extracted field deliberately NOT written, with the reason."""

    field_id: str = Field(..., description="KYC field id.")
    reason: str = Field(..., description="low_confidence | invalid_value | already_answered.")
    confidence: float = Field(..., description="Extraction confidence (0-1).")


class PrefillResponse(BaseModel):
    """Returned by POST /ocr/prefill — what was written and what remains."""

    session_id: str = Field(..., description="The updated interview session.")
    document_id: str = Field(..., description="The source document.")
    prefilled_count: int = Field(..., description="Fields written into the session.")
    prefilled: list[PrefilledFieldResponse] = Field(..., description="Written fields.")
    skipped: list[SkippedFieldResponse] = Field(
        ..., description="Fields left for the interview, with reasons."
    )
    remaining_required: list[str] = Field(
        ..., description="Required fields still unanswered after prefill."
    )
    progress_percentage: float = Field(..., description="Session progress now (0-100).")

    @classmethod
    def from_domain(cls, report: PrefillReport) -> "PrefillResponse":
        return cls(
            session_id=report.session_id,
            document_id=report.document_id,
            prefilled_count=len(report.prefilled),
            prefilled=[
                PrefilledFieldResponse(
                    field_id=p.field_id, value=p.value, confidence=p.confidence
                )
                for p in report.prefilled
            ],
            skipped=[
                SkippedFieldResponse(
                    field_id=s.field_id, reason=s.reason, confidence=s.confidence
                )
                for s in report.skipped
            ],
            remaining_required=list(report.remaining_required),
            progress_percentage=report.progress_percentage,
        )
