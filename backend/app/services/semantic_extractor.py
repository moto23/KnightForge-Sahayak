"""
SemanticExtractorService (Phase 13) — the AI half of the hybrid extraction
pipeline.

    Classification → OCR/layout → [deterministic FieldMapper]
                                → [THIS: Gemini semantic extraction]
                                → schema validation → canonical + extended

The deterministic FieldMapper is precise but label-bound. This service reads
the SAME OCR text and asks Gemini to map values SEMANTICALLY — "Permanent
Account Number", "Income Tax Number" and "e-PAN" all land on the canonical
`pan` field regardless of caption wording or position. Its output goes through
the SAME deterministic Validation Engine and ConfidenceEngine as every other
value: the AI proposes, the rules dispose. Readable values with no canonical
home are returned as extended-profile entries — nothing is discarded.

Graceful degradation is absolute: if Gemini is unconfigured, times out, or
returns garbage, `extract` returns empty tuples and the schema-based extractor
alone carries the document (exactly the pre-Phase-13 behavior).
"""

import logging
import re

from app.domain.canonical_schema import CanonicalSchemaRegistry, canonical_registry
from app.domain.enums import ExtractionMethod
from app.domain.extraction import OCRResult
from app.domain.intelligence import CanonicalValue, DocumentSchema, ExtraValue
from app.domain.validators.engine import ValidationEngine, validation_engine
from app.domain.validators.result import ValidationResult
from app.services.ai_service import AIService, AIUnavailableError
from app.services.confidence_engine import ConfidenceEngine, confidence_engine
from app.services.prompts.builder import PromptBundle

logger = logging.getLogger(__name__)

# Semantic extraction reads whole documents; cap the text we send and the JSON
# we get back so a 40-page statement can't blow the request.
_MAX_TEXT_CHARS = 9000
_MAX_OUTPUT_TOKENS = 2000
_MAX_EXTRAS = 25

_SYSTEM = (
    "You are a precise document field extraction engine for Indian KYC "
    "paperwork. You receive raw OCR text of ONE document and a catalog of "
    "target fields. Map values SEMANTICALLY: captions vary ('Permanent "
    "Account Number', 'Income Tax Number' and 'e-PAN' are all the PAN; 'DOB', "
    "'Birth Date' and 'Date of Birth' are all the date of birth) and values "
    "may sit far from their captions. Copy values EXACTLY as printed (fixing "
    "only obvious OCR character noise). Never invent, guess, or infer a value "
    "that is not present in the text. Reply ONLY with the requested JSON."
)

# Value-kind hints appended to the field catalog so the model normalizes
# formats the deterministic validators expect.
_KIND_HINTS = {
    "date": "format DD-MM-YYYY",
    "pan": "5 letters, 4 digits, 1 letter",
    "aadhaar": "12 digits, no spaces",
    "mobile": "10 digits, no country code",
    "pincode": "6 digits",
    "choice": "return one of the allowed options exactly",
}


class SemanticExtractorService:
    """Label-independent extraction via Gemini, judged by deterministic rules."""

    def __init__(
        self,
        ai: AIService,
        canonical: CanonicalSchemaRegistry = canonical_registry,
        validation: ValidationEngine = validation_engine,
        confidence: ConfidenceEngine = confidence_engine,
    ) -> None:
        self._ai = ai
        self._canonical = canonical
        self._validation = validation
        self._confidence = confidence

    @property
    def is_available(self) -> bool:
        return self._ai.is_available

    def extract(
        self, ocr: OCRResult, schema: DocumentSchema
    ) -> tuple[tuple[CanonicalValue, ...], tuple[ExtraValue, ...]]:
        """
        Semantic pass over one document. Returns (canonical values, extended
        values); both empty on ANY AI failure — callers never need a branch.
        """
        if not self._ai.is_available or not ocr.pages:
            return (), ()
        text = ocr.full_text[:_MAX_TEXT_CHARS].strip()
        if not text:
            return (), ()
        try:
            data = self._ai.complete_json(
                PromptBundle(system=_SYSTEM, user=self._prompt(text, schema)),
                max_output_tokens=_MAX_OUTPUT_TOKENS,
            )
        except AIUnavailableError as exc:
            logger.info("Semantic extraction skipped (%s): %s", schema.id, exc)
            return (), ()
        return self._parse(data, ocr, schema)

    # ------------------------------------------------------------------ #
    # Prompt
    # ------------------------------------------------------------------ #

    def _prompt(self, text: str, schema: DocumentSchema) -> str:
        catalog: list[str] = []
        for field in self._canonical.all_fields():
            kind_hint = _KIND_HINTS.get(field.value_kind, "")
            session_field = self._canonical.session_field(field.id)
            if field.value_kind == "choice" and session_field is not None:
                options = ", ".join(o.value for o in session_field.options)
                kind_hint = f"one of: {options}"
            catalog.append(
                f'- "{field.id}": {field.label}' + (f" ({kind_hint})" if kind_hint else "")
            )
        known_extras = [
            f'- "{rule.extra_key}": {rule.extra_label}'
            for rule in schema.fields
            if rule.is_extra
        ]
        extras_block = (
            "Known extended fields for this document type:\n" + "\n".join(known_extras)
            if known_extras
            else "No predefined extended fields — still report every other readable field."
        )
        return (
            f"Document type: {schema.label}\n\n"
            "Canonical KYC fields (use these exact keys under \"fields\"):\n"
            + "\n".join(catalog)
            + f"\n\n{extras_block}\n\n"
            "Return JSON exactly like:\n"
            '{"fields": {"<canonical_id>": "<value>", ...},\n'
            ' "extras": {"<snake_case_key>": {"label": "<Readable Name>", "value": "<value>"}, ...}}\n'
            "Rules: omit fields not present in the text. Put EVERY other real "
            "data value you can read (ids, numbers, dates, names, codes — e.g. "
            "a passport MRZ line, a customer id, a bank name) under \"extras\" "
            "with a sensible snake_case key. Do not include addresses of the "
            "issuer, instructions, or boilerplate.\n\n"
            f"OCR text:\n---\n{text}\n---"
        )

    # ------------------------------------------------------------------ #
    # Parse + judge — deterministic engines rule on every AI proposal.
    # ------------------------------------------------------------------ #

    def _parse(
        self, data: dict, ocr: OCRResult, schema: DocumentSchema
    ) -> tuple[tuple[CanonicalValue, ...], tuple[ExtraValue, ...]]:
        source = ocr.pages[0].source
        extras_labels = {
            rule.extra_key: rule.extra_label or rule.extra_key
            for rule in schema.fields
            if rule.is_extra and rule.extra_key
        }
        values: list[CanonicalValue] = []
        raw_fields = data.get("fields")
        if isinstance(raw_fields, dict):
            for canonical_id, raw in raw_fields.items():
                value = self._clean(raw)
                if not value or self._canonical.get(canonical_id) is None:
                    continue
                page_number, page_confidence = self._locate(value, ocr)
                session_field = self._canonical.session_field(canonical_id)
                if session_field is not None:
                    validation = self._validation.validate_field(session_field, value)
                else:
                    validation = ValidationResult.ok("No session mapping — accepted as-is.")
                confidence, _ = self._confidence.score(
                    page_confidence=page_confidence,
                    source=source,
                    method=ExtractionMethod.SEMANTIC,
                    validation=validation,
                    value=value,
                )
                values.append(
                    CanonicalValue(
                        canonical_id=canonical_id,
                        value=value,
                        confidence=confidence,
                        valid=validation.valid,
                        validation_message=validation.message,
                        method=ExtractionMethod.SEMANTIC,
                        source=source,
                        page_number=page_number,
                        document_id=ocr.document_id,
                    )
                )

        extras: list[ExtraValue] = []
        raw_extras = data.get("extras")
        if isinstance(raw_extras, dict):
            for key, entry in list(raw_extras.items())[:_MAX_EXTRAS]:
                if isinstance(entry, dict):
                    value = self._clean(entry.get("value"))
                    label = str(entry.get("label") or "").strip()
                else:  # tolerate the model flattening {"key": "value"}
                    value = self._clean(entry)
                    label = ""
                safe_key = re.sub(r"[^a-z0-9_]+", "_", str(key).strip().lower()).strip("_")
                if not value or not safe_key:
                    continue
                page_number, page_confidence = self._locate(value, ocr)
                validation = ValidationResult.ok("Extended-profile value.")
                confidence, _ = self._confidence.score(
                    page_confidence=page_confidence,
                    source=source,
                    method=ExtractionMethod.SEMANTIC,
                    validation=validation,
                    value=value,
                )
                extras.append(
                    ExtraValue(
                        key=safe_key,
                        label=extras_labels.get(safe_key)
                        or label
                        or safe_key.replace("_", " ").title(),
                        value=value,
                        confidence=confidence,
                        method=ExtractionMethod.SEMANTIC,
                        source=source,
                        page_number=page_number,
                        document_id=ocr.document_id,
                    )
                )
        logger.info(
            "Semantic extraction (%s) for %s: %d canonical, %d extended",
            schema.id,
            ocr.document_id,
            len(values),
            len(extras),
        )
        return tuple(values), tuple(extras)

    @staticmethod
    def _clean(raw: object) -> str:
        if raw is None:
            return ""
        value = re.sub(r"\s{2,}", " ", str(raw)).strip()
        # The model must copy, not narrate — drop obvious refusal/None strings.
        if value.lower() in {"", "null", "none", "n/a", "not present", "unknown"}:
            return ""
        return value[:120]

    @staticmethod
    def _locate(value: str, ocr: OCRResult) -> tuple[int, float]:
        """Attribute a value to the page it appears on (for provenance)."""
        needle = re.sub(r"\s+", "", value).casefold()[:24]
        for page in ocr.pages:
            if needle and needle in re.sub(r"\s+", "", page.text).casefold():
                return page.page_number, page.confidence
        first = ocr.pages[0] if ocr.pages else None
        return (first.page_number if first else 1, ocr.mean_confidence)


# Composed in core/dependencies.py (needs the shared AIService instance).
