"""
ExtractionEngine — convert raw document text into structured KYC fields.

Third stage of the Phase 7 pipeline (requirement 5). Consumes the OCRResult's
raw text (the ONLY consumer — raw text never crosses the API boundary) and
produces ExtractedField records keyed to the KYC schema registry.

Extraction is deterministic and schema-driven; there is no AI here. Three
matching strategies, in decreasing strength:

    PATTERN — the value's format is unambiguous document-wide (PAN, email…).
    LABEL   — the value follows the field's printed label ("PAN : ABCDE1234F").
    OPTION  — a schema option word appears on the field's labelled line
              ("Gender : Male"). Ambiguous lines (several options present,
              e.g. an unticked blank form) are deliberately NOT extracted.

Every extracted value is scored by the ConfidenceEngine and judged by the
deterministic Validation Engine — invalid values are still reported (with the
failure) but never marked `accepted`. Fields the engine cannot find simply
appear in `missing_required`; a partially readable document degrades to a
partial extraction, never an error (requirement 11).
"""

import logging
import re
from dataclasses import dataclass, field as dc_field

from app.domain.enums import ExtractionMethod
from app.domain.extraction import ExtractedField, ExtractionResult, OCRPage, OCRResult
from app.domain.kyc_schema import KYCSchemaRegistry, kyc_registry
from app.domain.validators.engine import ValidationEngine, validation_engine
from app.services.confidence_engine import ConfidenceEngine, confidence_engine

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Value patterns — formats specific enough to trust inside a label's remainder
# (and, where `document_wide` below allows, anywhere in the document).
# --------------------------------------------------------------------------- #

_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "pan": re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b"),
    "aadhaar": re.compile(r"\b(\d{4}[ -]?\d{4}[ -]?\d{4})\b"),
    "mobile": re.compile(r"(?:\+?91[\s-]?)?\b([6-9]\d{9})\b"),
    "email": re.compile(r"\b([\w.+-]+@[\w-]+\.[\w.-]+)\b", re.IGNORECASE),
    "pincode": re.compile(r"\b([1-9]\d{5})\b"),
    "date": re.compile(r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})\b"),
    "number": re.compile(r"\b([\d,]{3,})\b"),
}

# Formats unambiguous enough to extract WITHOUT a label anywhere in the text.
# (A bare 6-digit number could be anything; a PAN or an email cannot.)
_DOCUMENT_WIDE = {"pan", "email", "aadhaar", "mobile"}

# Candidate text values containing any of these words are form instructions,
# not user data ("Please tick", "see guidelines overleaf"…).
_JUNK_WORDS = re.compile(
    r"\b(please|tick|specify|mandatory|applicable|overleaf|guideline|guidelines|"
    r"block|letters|attach|enclose|self.attested|photograph|organization|"
    r"designation|intermediary|stamp|seal|office|verification|staff|details|"
    r"heads|definition|refer|town|village|code|issued|following|documents|"
    r"e\.?g)\b",
    re.IGNORECASE,
)

# Free-text label extraction only trusts short, form-like lines. Guideline
# prose ("...State Industrial Development Corporation...") flows well past
# this; a real form line ("State  MAHARASHTRA") never does.
_MAX_FORM_LINE_CHARS = 80

# Pages that are printed INSTRUCTIONS, not the form itself (every Indian KYC
# form ships one). Free-text extraction is disabled for the whole page;
# unambiguous typed patterns (PAN, email…) are still allowed.
_INSTRUCTION_PAGE = re.compile(
    r"important\s+points|general\s+instructions|instructions?\s+for\s+filling",
    re.IGNORECASE,
)

# A candidate that IS just another form caption (survives span-claiming when
# OCR splits lines oddly) — never real data.
_CAPTION_VALUES = {
    "name", "state", "country", "date", "place", "city", "pin code", "pincode",
    "fax", "tel", "email", "e mail", "signature", "photograph", "yes", "no",
}

# Phrases that identify the CVL Individual KYC form (fuzz-tolerant).
_KYC_MARKERS = (
    re.compile(r"know\s+your\s+client", re.IGNORECASE),
    re.compile(r"\bKYC\b"),
    re.compile(r"application\s+form", re.IGNORECASE),
    re.compile(r"identity\s+details", re.IGNORECASE),
)


@dataclass(frozen=True)
class FieldSpec:
    """
    How to find ONE schema field in document text.

    `labels` are the captions printed on the form (aliases included for common
    OCR misreads); `value_key` picks a _VALUE_PATTERNS entry to pull a typed
    value out of the label's remainder (None = take the remainder as free text
    or, for option/boolean fields, match schema options in it).
    """

    field_id: str
    labels: tuple[str, ...]
    value_key: str | None = None
    boolean_options: tuple[str, ...] = dc_field(default=())  # yes/no style fields


# Order matters twice: longer/more specific labels must be claimed before the
# generic ones they contain ("marital status" before "status", "related to a
# politically exposed person" before "politically exposed person").
_FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("father_spouse_name", ("father's/spouse name", "father spouse name", "fathers name")),
    FieldSpec("full_name", ("name of applicant", "full name", "name")),
    FieldSpec("marital_status", ("marital status",)),
    FieldSpec("date_of_birth", ("date of birth", "dob"), value_key="date"),
    FieldSpec("gender", ("gender",)),
    FieldSpec("nationality", ("nationality",)),
    FieldSpec("residential_status", ("residential status", "status")),
    FieldSpec("pan", ("pan",), value_key="pan"),
    FieldSpec("aadhaar", ("aadhaar", "uid", "unique identification number"), value_key="aadhaar"),
    FieldSpec("correspondence_address", ("address for correspondence", "correspondence address", "address")),
    FieldSpec("city", ("city/town/village", "city town village", "city")),
    FieldSpec("state", ("state",)),
    FieldSpec("pincode", ("pin code", "pincode"), value_key="pincode"),
    FieldSpec("country", ("country",)),
    FieldSpec("mobile", ("mobile",), value_key="mobile"),
    FieldSpec("email", ("e-mail id", "email id", "e-mail", "email"), value_key="email"),
    FieldSpec("poa_document", ("proof of address",)),
    FieldSpec("gross_annual_income", ("gross annual income", "annual income")),
    FieldSpec("net_worth", ("net-worth", "net worth"), value_key="number"),
    FieldSpec("occupation", ("occupation",)),
    FieldSpec(
        "is_pep_related",
        ("related to a politically exposed person", "related to a pep"),
        boolean_options=("yes", "no"),
    ),
    FieldSpec(
        "is_pep",
        ("politically exposed person", "pep"),
        boolean_options=("yes", "no"),
    ),
    FieldSpec("declaration_place", ("place",)),
    FieldSpec("declaration_date", ("date",), value_key="date"),
)


def _label_regex(label: str) -> re.Pattern[str]:
    """
    Build a fuzz-tolerant regex for a printed label.

    Each label word must appear in order, separated by at most 3 arbitrary
    characters — absorbing OCR noise like "Father'iSpouse Name" or "E-Mailld"
    without matching unrelated text. Both ends are anchored to word boundaries
    so "State" never matches inside "Statement".
    """
    words = [re.escape(w) for w in re.findall(r"[a-z0-9]+", label.lower())]
    return re.compile(
        r"\b" + r".{0,3}?".join(words) + r"(?![a-z0-9])", re.IGNORECASE
    )


# Compile once at import.
_LABEL_REGEXES: dict[str, tuple[re.Pattern[str], ...]] = {
    spec.field_id: tuple(_label_regex(l) for l in spec.labels) for spec in _FIELD_SPECS
}


@dataclass(frozen=True)
class _Candidate:
    """One raw value found for a field, before scoring/validation."""

    field_id: str
    value: str
    method: ExtractionMethod
    page: OCRPage


class ExtractionEngine:
    """Deterministic, schema-driven KYC field extraction from raw text."""

    def __init__(
        self,
        registry: KYCSchemaRegistry = kyc_registry,
        engine: ValidationEngine = validation_engine,
        confidence: ConfidenceEngine = confidence_engine,
    ) -> None:
        self._registry = registry
        self._validation = engine
        self._confidence = confidence

    def extract(self, ocr: OCRResult) -> ExtractionResult:
        """
        Turn one document's raw text into scored, validated KYC fields.

        Never raises for content problems: an unreadable or non-KYC document
        simply yields fewer (or zero) fields plus honest warnings.
        """
        candidates: dict[str, _Candidate] = {}
        for page in ocr.pages:
            if not page.text:
                continue
            for candidate in self._extract_from_page(page):
                # First (page-order) hit per field wins — applicant sections
                # precede office-use sections on real forms.
                candidates.setdefault(candidate.field_id, candidate)

        fields = tuple(
            self._score_and_validate(c) for c in candidates.values()
        )
        found_ids = {f.field_id for f in fields}
        missing_required = tuple(
            f.id for f in self._registry.required_fields() if f.id not in found_ids
        )

        is_kyc = self._looks_like_kyc(ocr.full_text)
        warnings = self._build_warnings(ocr, fields, missing_required, is_kyc)

        logger.info(
            "Extraction for %s: %d fields found (%d accepted), %d required missing",
            ocr.document_id,
            len(fields),
            sum(1 for f in fields if f.accepted),
            len(missing_required),
        )
        return ExtractionResult(
            document_id=ocr.document_id,
            is_kyc_form=is_kyc,
            fields=fields,
            missing_required=missing_required,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ #
    # Per-page extraction
    # ------------------------------------------------------------------ #

    def _extract_from_page(self, page: OCRPage) -> list[_Candidate]:
        """Run label/option extraction line-by-line, then document-wide patterns."""
        candidates: list[_Candidate] = []
        claimed: set[str] = set()

        # An instructions/guidelines page mentions field names in running
        # prose — free-text and option extraction there produce garbage.
        instruction_page = bool(_INSTRUCTION_PAGE.search(page.text))

        for line in page.text.splitlines():
            if not line.strip():
                continue
            # Long lines are guideline prose, not form rows — only typed
            # patterns (never free text) may be pulled from them.
            prose_line = instruction_page or len(line.strip()) > _MAX_FORM_LINE_CHARS
            for field_id, remainder in self._segment_line(line):
                if field_id in claimed:
                    continue
                candidate = self._value_from_remainder(
                    field_id, remainder, page, allow_free_text=not prose_line
                )
                if candidate is not None:
                    candidates.append(candidate)
                    claimed.add(field_id)

        # Document-wide pattern sweep for unambiguous formats the labels
        # missed (e.g. a PAN-card photo with no printed "PAN" caption).
        for spec in _FIELD_SPECS:
            if spec.field_id in claimed or spec.value_key not in _DOCUMENT_WIDE:
                continue
            match = _VALUE_PATTERNS[spec.value_key].search(page.text)
            if match:
                candidates.append(
                    _Candidate(
                        field_id=spec.field_id,
                        value=self._normalize_typed(spec.value_key, match.group(1)),
                        method=ExtractionMethod.PATTERN,
                        page=page,
                    )
                )
                claimed.add(spec.field_id)
        return candidates

    def _segment_line(self, line: str) -> list[tuple[str, str]]:
        """
        Find every field label on one line and slice the line into
        (field_id, remainder) segments.

        All label matches are located first, overlaps resolved in favor of the
        longer (more specific) match, then each label's remainder runs to the
        start of the next claimed label — so "Gender: Male  Marital Status:
        Single" yields two clean segments.
        """
        hits: list[tuple[int, int, str]] = []  # (start, end, field_id)
        for spec in _FIELD_SPECS:
            for regex in _LABEL_REGEXES[spec.field_id]:
                match = regex.search(line)
                if match:
                    hits.append((match.start(), match.end(), spec.field_id))
                    break  # first alias hit is enough for this field

        # Longer matches claim their span first; contained/overlapping shorter
        # labels ("Name" inside "Father's/Spouse Name") are dropped.
        hits.sort(key=lambda h: (-(h[1] - h[0]), h[0]))
        claimed_spans: list[tuple[int, int, str]] = []
        for start, end, field_id in hits:
            if any(start < c_end and end > c_start for c_start, c_end, _ in claimed_spans):
                continue
            claimed_spans.append((start, end, field_id))

        claimed_spans.sort(key=lambda s: s[0])
        segments: list[tuple[str, str]] = []
        for i, (start, end, field_id) in enumerate(claimed_spans):
            next_start = claimed_spans[i + 1][0] if i + 1 < len(claimed_spans) else len(line)
            segments.append((field_id, line[end:next_start]))
        return segments

    def _value_from_remainder(
        self, field_id: str, remainder: str, page: OCRPage, allow_free_text: bool = True
    ) -> _Candidate | None:
        """Turn the text after a label into a typed candidate value, or None."""
        spec = next(s for s in _FIELD_SPECS if s.field_id == field_id)
        schema_field = self._registry.get_field(field_id)
        if schema_field is None:  # spec/schema drift guard
            return None

        # Boolean fields: look for an unambiguous yes/no after the label.
        if spec.boolean_options:
            found = {
                opt for opt in spec.boolean_options
                if re.search(rf"\b{opt}\b", remainder, re.IGNORECASE)
            }
            if len(found) != 1:
                return None  # blank or ambiguous — leave for the interview
            return _Candidate(field_id, found.pop(), ExtractionMethod.OPTION, page)

        # Choice fields: exactly ONE schema option word must appear. A blank
        # printed form shows ALL options ("[ ] Male [ ] Female") — ambiguous,
        # so nothing is extracted, which is precisely the safe behavior.
        if schema_field.options:
            matched = [
                opt for opt in schema_field.options
                if re.search(rf"\b{re.escape(opt.label)}\b", remainder, re.IGNORECASE)
                or re.search(rf"\b{re.escape(opt.value)}\b", remainder, re.IGNORECASE)
            ]
            if len(matched) != 1:
                return None
            return _Candidate(field_id, matched[0].value, ExtractionMethod.OPTION, page)

        # Typed value: pull it out of the remainder with the format pattern.
        if spec.value_key:
            match = _VALUE_PATTERNS[spec.value_key].search(remainder)
            if not match:
                return None
            value = self._normalize_typed(spec.value_key, match.group(1))
            return _Candidate(field_id, value, ExtractionMethod.LABEL, page)

        # Free text: clean the remainder and junk-filter it (prose lines are
        # never a source of free-text values — typed patterns above only).
        if not allow_free_text:
            return None
        value = self._clean_text(remainder)
        if not value:
            return None
        return _Candidate(field_id, value, ExtractionMethod.LABEL, page)

    # ------------------------------------------------------------------ #
    # Scoring + validation (requirements 6 & 7)
    # ------------------------------------------------------------------ #

    def _score_and_validate(self, candidate: _Candidate) -> ExtractedField:
        """Attach the Validation Engine verdict and the final confidence score."""
        schema_field = self._registry.get_field(candidate.field_id)
        validation = self._validation.validate_field(schema_field, candidate.value)
        confidence, accepted = self._confidence.score(
            page_confidence=candidate.page.confidence,
            source=candidate.page.source,
            method=candidate.method,
            validation=validation,
            value=candidate.value,
        )
        return ExtractedField(
            field_id=candidate.field_id,
            value=candidate.value,
            confidence=confidence,
            source=candidate.page.source,
            method=candidate.method,
            page_number=candidate.page.page_number,
            validation_result=validation,
            accepted=accepted,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _normalize_typed(self, value_key: str, raw: str) -> str:
        """Canonicalize typed values (digits squeezed, PAN uppercased…)."""
        if value_key == "aadhaar":
            return re.sub(r"[ -]", "", raw)
        if value_key in ("mobile", "pincode"):
            return raw.strip()
        if value_key == "pan":
            return raw.upper()
        if value_key == "number":
            return raw.replace(",", "")
        return raw.strip()

    def _clean_text(self, raw: str) -> str:
        """
        Reduce a free-text remainder to a plausible user value.

        Drops parenthetical instructions, box-drawing/underscore artifacts,
        leading separators, and anything that looks like form boilerplate.
        """
        value = re.sub(r"\([^)]*\)", " ", raw)              # printed instructions
        value = re.sub(r"[_|\[\]{}<>~*#=]+", " ", value)    # form-box artifacts
        value = value.strip(" \t:;.,-–—/\\'\"")
        value = re.sub(r"\s{2,}", " ", value).strip()
        if len(value) < 2 or len(value) > 80:
            return ""
        if not re.search(r"[A-Za-z0-9]", value):
            return ""
        if _JUNK_WORDS.search(value):
            return ""
        if value[0].islower():
            # KYC forms are filled in BLOCK LETTERS; a remainder starting
            # lowercase is almost always the tail of a printed sentence.
            return ""
        if value.lower() in _CAPTION_VALUES:
            return ""
        return value

    def _looks_like_kyc(self, text: str) -> bool:
        """At least two KYC markers must appear for a positive identification."""
        return sum(1 for marker in _KYC_MARKERS if marker.search(text)) >= 2

    def _build_warnings(
        self,
        ocr: OCRResult,
        fields: tuple[ExtractedField, ...],
        missing_required: tuple[str, ...],
        is_kyc: bool,
    ) -> tuple[str, ...]:
        """Honest, human-readable caveats about this extraction."""
        warnings: list[str] = []
        if not is_kyc:
            warnings.append(
                "The document does not look like the CVL Individual KYC form; "
                "only unambiguous values (PAN, email, etc.) were extracted."
            )
        if ocr.total_chars == 0:
            warnings.append("No text could be read from the document.")
        elif not fields:
            warnings.append(
                "No KYC field values were found — the form appears to be blank "
                "or unreadable."
            )
        elif missing_required:
            warnings.append(
                f"Partial extraction: {len(missing_required)} required field(s) "
                "were not found and will be asked in the interview."
            )
        rejected = [f for f in fields if not f.accepted]
        if rejected:
            warnings.append(
                f"{len(rejected)} extracted value(s) failed validation or scored "
                "below the confidence threshold and will NOT be prefilled."
            )
        return tuple(warnings)


# Stateless singleton.
extraction_engine = ExtractionEngine()
