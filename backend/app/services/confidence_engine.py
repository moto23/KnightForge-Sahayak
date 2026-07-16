"""
ConfidenceEngine — one deterministic score for every extracted value.

Fourth stage of the Phase 7 pipeline. Combines four independent signals into
a single 0-1 confidence, and rules on whether the value is trustworthy enough
for automatic prefill:

    base       — the OCR page's own mean word confidence (1.0 for a PDF text
                 layer: digital text has no recognition noise)
    method     — how the value was matched: an unambiguous format pattern
                 beats a label match beats a bare option word
    validation — a value the deterministic Validation Engine REJECTED is
                 hard-capped: it can never reach the prefill threshold
    shape      — tiny heuristic penalties for suspicious values (digits in a
                 name-like field, single-word free text, etc.)

The engine is pure arithmetic — no I/O, no AI, no randomness — so identical
inputs always yield identical scores, and the whole policy is testable in
isolation.
"""

from app.core.config import Settings, settings
from app.domain.enums import ExtractionMethod, ExtractionSource
from app.domain.validators.result import ValidationResult

# Multipliers per matching method — how strong the evidence is that this value
# belongs to this field.
_METHOD_WEIGHT: dict[ExtractionMethod, float] = {
    ExtractionMethod.PATTERN: 1.00,   # format is unambiguous (PAN, email…)
    ExtractionMethod.LABEL: 0.95,     # found right after the field's caption
    ExtractionMethod.OPTION: 0.90,    # one schema option word on the line
}

# A value that FAILED deterministic validation can never be prefilled:
# cap it well below any sane threshold while still ranking candidates.
_INVALID_CAP = 0.35

# Small boost when validation actively CONFIRMS a strict format (checksummed
# Aadhaar, PAN pattern…) — distinct from merely "no rule failed".
_STRICT_VALID_BONUS = 1.05
_STRICT_VALID_CODES = {
    "valid_pan", "valid_aadhaar", "valid_mobile", "valid_email",
    "valid_pincode", "valid_date", "valid_dob",
}


class ConfidenceEngine:
    """Score extracted values and decide if they clear the prefill bar."""

    def __init__(self, config: Settings = settings) -> None:
        self._threshold = config.PREFILL_CONFIDENCE_THRESHOLD

    @property
    def threshold(self) -> float:
        """The minimum confidence required for automatic prefill."""
        return self._threshold

    def score(
        self,
        page_confidence: float,
        source: ExtractionSource,
        method: ExtractionMethod,
        validation: ValidationResult,
        value: str,
    ) -> tuple[float, bool]:
        """
        Return (final confidence 0-1, accepted for prefill?).

        `accepted` is True only when the value is VALID and the final score
        clears the configured threshold — the single gate the
        SessionPrefillService trusts.
        """
        # Digital text layers are exact; OCR pages carry their measured noise.
        base = 1.0 if source == ExtractionSource.PDF_TEXT_LAYER else page_confidence

        confidence = base * _METHOD_WEIGHT[method] * self._shape_factor(value)

        if not validation.valid:
            confidence = min(confidence, _INVALID_CAP)
        elif validation.code in _STRICT_VALID_CODES:
            confidence = min(1.0, confidence * _STRICT_VALID_BONUS)

        confidence = round(max(0.0, min(1.0, confidence)), 4)
        accepted = validation.valid and confidence >= self._threshold
        return confidence, accepted

    def _shape_factor(self, value: str) -> float:
        """
        Penalize value shapes that usually indicate OCR noise.

        Deliberately mild — the Validation Engine is the real gatekeeper; this
        only separates "clean" from "smells like noise" among valid values.
        """
        factor = 1.0
        stripped = value.strip()
        if len(stripped) <= 2:
            factor *= 0.85                    # very short values are fragile
        letters = sum(c.isalpha() for c in stripped)
        digits = sum(c.isdigit() for c in stripped)
        if letters and digits and not any(c.isdigit() for c in stripped[:1]):
            # Mixed letters+digits is normal for PAN/addresses but suspicious
            # in general — a tiny nudge only.
            factor *= 0.97
        if "  " in stripped or stripped != " ".join(stripped.split()):
            factor *= 0.95                    # ragged whitespace = OCR seams
        return factor


# Stateless singleton (reads only immutable settings).
confidence_engine = ConfidenceEngine()
