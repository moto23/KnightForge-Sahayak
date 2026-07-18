"""
FieldMapper (Phase 11) — the ONE schema-driven extractor for every document.

Universal Document Intelligence core rule: there is no extract_cvl(),
extract_sbi() or extract_pan(). There is exactly

    extract_document(ocr, schema) -> canonical values

and the DocumentSchema (loaded from JSON) is the ONLY thing that varies
between a CVL form, an SBI form and an Aadhaar card. Labels, aliases and
canonical mappings live in the schema files — never in this code.

Matching strategies, in decreasing strength (same philosophy as the Phase 7
engine, generalized to arbitrary schemas):

    PATTERN — the value's format is unambiguous document-wide (PAN, email…);
              enabled per-rule via `document_wide` in the schema.
    LABEL   — the value follows one of the field's printed labels.
    OPTION  — exactly one schema option word appears (choice fields such as
              gender); ambiguous lines (a blank form showing all options)
              are deliberately NOT extracted.

Every value is normalized, scored by the existing ConfidenceEngine, and judged
by the existing deterministic Validation Engine (against the canonical field's
mapped interview-session field) — nothing new is invented for scoring or
validation. Fields the mapper cannot find are simply absent; a partially
readable document degrades to a partial extraction, never an error.
"""

import logging
import re

from app.domain.canonical_schema import CanonicalSchemaRegistry, canonical_registry
from app.domain.enums import ExtractionMethod
from app.domain.extraction import OCRPage, OCRResult
from app.domain.intelligence import (
    CanonicalValue,
    DocumentSchema,
    ExtraValue,
    SchemaFieldRule,
)
from app.domain.validators.engine import ValidationEngine, validation_engine
from app.domain.validators.result import ValidationResult
from app.services.confidence_engine import ConfidenceEngine, confidence_engine

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Typed value patterns — formats specific enough to trust inside a label's
# remainder (and, where a rule's `document_wide` allows, anywhere on the page).
# --------------------------------------------------------------------------- #

_VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "pan": re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b"),
    "aadhaar": re.compile(r"\b(\d{4}[ -]?\d{4}[ -]?\d{4})\b"),
    "mobile": re.compile(r"(?:\+?91[\s-]?)?\b([6-9]\d{9})\b"),
    "email": re.compile(r"\b([\w.+-]+@[\w-]+\.[\w.-]+)\b", re.IGNORECASE),
    "pincode": re.compile(r"\b([1-9]\d{5})\b"),
    "date": re.compile(r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{4})\b"),
    "number": re.compile(r"\b([\d,]{3,})\b"),
    # Extended-profile formats (evidence outside the canonical KYC model).
    "passport_no": re.compile(r"\b([A-Z][0-9]{7})\b"),
    "epic": re.compile(r"\b([A-Z]{3}[0-9]{7})\b"),
    "ifsc": re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b"),
    "account_no": re.compile(r"\b(\d{9,18})\b"),
    "mrz": re.compile(r"(P<[A-Z0-9<]{20,})"),
}

# Free-text values containing these words are printed form instructions,
# not user data ("Please tick", "see guidelines overleaf"…).
_JUNK_WORDS = re.compile(
    r"\b(please|tick|specify|mandatory|applicable|overleaf|guideline|guidelines|"
    r"block|letters|attach|enclose|self.attested|photograph|organization|"
    r"designation|intermediary|stamp|seal|office|verification|staff|details|"
    r"heads|definition|refer|code|issued|following|documents|signature|"
    r"authority|e\.?g)\b",
    re.IGNORECASE,
)

# A candidate that IS just another form caption — never real data.
_CAPTION_VALUES = {
    "name", "state", "country", "date", "place", "city", "pin code", "pincode",
    "fax", "tel", "email", "e mail", "signature", "photograph", "yes", "no",
    "address", "gender", "male", "female",
}

# Free-text label extraction only trusts short, form-like lines; guideline
# prose flows well past this.
_MAX_FORM_LINE_CHARS = 80

# Pages that are printed INSTRUCTIONS, not the form itself. Free-text
# extraction is disabled for the whole page; typed patterns still run.
_INSTRUCTION_PAGE = re.compile(
    r"important\s+points|general\s+instructions|instructions?\s+for\s+filling",
    re.IGNORECASE,
)


def fuzzy_phrase_regex(phrase: str) -> re.Pattern[str]:
    """
    Build a fuzz-tolerant regex for a printed phrase.

    Each word must appear in order, separated by at most 3 arbitrary
    characters — absorbing OCR noise like "Father'iSpouse Name" without
    matching unrelated text. Both ends are anchored to word boundaries so
    "state" never matches inside "statement". Shared with the classifier.
    """
    words = [re.escape(w) for w in re.findall(r"[a-z0-9]+", phrase.lower())]
    return re.compile(r"\b" + r".{0,3}?".join(words) + r"(?![a-z0-9])", re.IGNORECASE)


class _Candidate:
    """One raw value found for a canonical field, before scoring/validation."""

    __slots__ = ("canonical_id", "value", "method", "page")

    def __init__(
        self, canonical_id: str, value: str, method: ExtractionMethod, page: OCRPage
    ) -> None:
        self.canonical_id = canonical_id
        self.value = value
        self.method = method
        self.page = page


class FieldMapper:
    """Deterministic, schema-driven canonical extraction — one pipeline for all."""

    def __init__(
        self,
        canonical: CanonicalSchemaRegistry = canonical_registry,
        validation: ValidationEngine = validation_engine,
        confidence: ConfidenceEngine = confidence_engine,
    ) -> None:
        self._canonical = canonical
        self._validation = validation
        self._confidence = confidence
        # Compiled label/marker regexes cached per schema id (schemas are frozen).
        self._label_cache: dict[str, list[tuple[SchemaFieldRule, list[re.Pattern[str]]]]] = {}
        self._header_cache: dict[str, list[re.Pattern[str]]] = {}

    # ------------------------------------------------------------------ #
    # THE extraction entry point — same code path for every document type.
    # ------------------------------------------------------------------ #

    def extract_document(
        self, ocr: OCRResult, schema: DocumentSchema
    ) -> tuple[tuple[CanonicalValue, ...], tuple[ExtraValue, ...]]:
        """
        Map one document's raw text using `schema` into (canonical values,
        extended-profile values). Everything readable is kept: values with a
        canonical KYC home feed the interview/merge machinery; everything
        else (passport numbers, IFSC codes…) lands in the extended profile —
        extracted data is never discarded for being outside the KYC schema.

        Never raises for content problems: an unreadable or mismatched
        document simply yields fewer (or zero) values.
        """
        compiled = self._compiled_rules(schema)
        headers = self._header_regexes(schema)
        rule_by_target = {rule.target_id: rule for rule, _ in compiled}
        candidates: dict[str, _Candidate] = {}
        for page in ocr.pages:
            if not page.text:
                continue
            for candidate in self._extract_from_page(page, compiled, headers):
                # First (page-order) hit per field wins — applicant sections
                # precede office-use sections on real forms.
                candidates.setdefault(candidate.canonical_id, candidate)

        values: list[CanonicalValue] = []
        extras: list[ExtraValue] = []
        for target_id, candidate in candidates.items():
            scored = self._score_and_validate(candidate, ocr.document_id)
            rule = rule_by_target.get(target_id)
            if rule is not None and rule.is_extra:
                extras.append(
                    ExtraValue(
                        key=rule.extra_key or target_id,
                        label=rule.extra_label or (rule.extra_key or target_id).replace("_", " ").title(),
                        value=scored.value,
                        confidence=scored.confidence,
                        method=scored.method,
                        source=scored.source,
                        page_number=scored.page_number,
                        document_id=scored.document_id,
                    )
                )
            else:
                values.append(scored)
        logger.info(
            "Schema '%s' extraction for %s: %d canonical values (%d valid), %d extended",
            schema.id,
            ocr.document_id,
            len(values),
            sum(1 for v in values if v.valid),
            len(extras),
        )
        return tuple(values), tuple(extras)

    # ------------------------------------------------------------------ #
    # Per-page extraction
    # ------------------------------------------------------------------ #

    def _extract_from_page(
        self,
        page: OCRPage,
        compiled: list[tuple[SchemaFieldRule, list[re.Pattern[str]]]],
        headers: list[re.Pattern[str]],
    ) -> list[_Candidate]:
        """Run label/option extraction line-by-line, then document-wide patterns."""
        candidates: list[_Candidate] = []
        claimed: set[str] = set()
        instruction_page = bool(_INSTRUCTION_PAGE.search(page.text))
        lines = page.text.splitlines()

        for index, line in enumerate(lines):
            if not line.strip():
                continue
            # Long lines are guideline prose, not form rows — only typed
            # patterns (never free text) may be pulled from them. A line
            # containing the schema's own STRONG classification marker is an
            # issuer header ("STATE BANK OF INDIA"), never a data row.
            header_line = any(regex.search(line) for regex in headers)
            prose_line = (
                instruction_page
                or header_line
                or len(line.strip()) > _MAX_FORM_LINE_CHARS
            )
            segments = self._segment_line(line, compiled)
            for position, (rule, remainder) in enumerate(segments):
                if rule.target_id in claimed:
                    continue
                candidate = self._value_from_remainder(
                    rule, remainder, page, allow_free_text=not prose_line
                )
                if (
                    candidate is None
                    and position == len(segments) - 1
                    and not _clean_text(remainder)  # "" or caption residue like "(s)"
                ):
                    # ID-card layout: the caption sits on its own line and the
                    # value is printed on the NEXT line ("Name ⏎ PRASAD NATHE").
                    candidate = self._value_from_next_line(
                        rule, lines, index, page, compiled
                    )
                if candidate is not None:
                    candidates.append(candidate)
                    claimed.add(rule.target_id)

        # Document-wide sweep for rules whose format (or single-option match)
        # is unambiguous without a printed label — a PAN card photo has no
        # "PAN" caption, an Aadhaar card states just "MALE".
        for rule, _ in compiled:
            if rule.target_id in claimed or not rule.document_wide:
                continue
            candidate = self._document_wide_value(rule, page)
            if candidate is not None:
                candidates.append(candidate)
                claimed.add(rule.target_id)
        return candidates

    def _segment_line(
        self,
        line: str,
        compiled: list[tuple[SchemaFieldRule, list[re.Pattern[str]]]],
    ) -> list[tuple[SchemaFieldRule, str]]:
        """
        Find every schema label on one line and slice it into (rule, remainder)
        segments. Longer (more specific) label matches claim their span first,
        then each remainder runs to the start of the next claimed label.
        """
        hits: list[tuple[int, int, SchemaFieldRule]] = []
        for rule, regexes in compiled:
            for regex in regexes:
                match = regex.search(line)
                if match:
                    hits.append((match.start(), match.end(), rule))
                    break  # first alias hit is enough for this rule

        hits.sort(key=lambda h: (-(h[1] - h[0]), h[0]))
        claimed_spans: list[tuple[int, int, SchemaFieldRule]] = []
        for start, end, rule in hits:
            if any(start < c_end and end > c_start for c_start, c_end, _ in claimed_spans):
                continue
            claimed_spans.append((start, end, rule))

        claimed_spans.sort(key=lambda s: s[0])
        segments: list[tuple[SchemaFieldRule, str]] = []
        for i, (start, end, rule) in enumerate(claimed_spans):
            next_start = claimed_spans[i + 1][0] if i + 1 < len(claimed_spans) else len(line)
            segments.append((rule, line[end:next_start]))
        return segments

    def _value_from_remainder(
        self,
        rule: SchemaFieldRule,
        remainder: str,
        page: OCRPage,
        allow_free_text: bool,
    ) -> _Candidate | None:
        """Turn the text after a label into a typed candidate value, or None."""
        kind = self._value_kind(rule)

        # Choice fields: exactly ONE of the session field's options must
        # appear. A blank printed form shows ALL options — ambiguous, so
        # nothing is extracted, which is precisely the safe behavior.
        # (Choice matching needs a canonical session field — never an extra.)
        if kind == "choice":
            if rule.canonical is None:
                return None
            matched = self._match_single_option(rule.canonical, remainder)
            if matched is None:
                return None
            return _Candidate(rule.target_id, matched, ExtractionMethod.OPTION, page)

        # Typed value: pull it out of the remainder with the format pattern.
        if kind in _VALUE_PATTERNS:
            match = _VALUE_PATTERNS[kind].search(remainder)
            if not match:
                return None
            value = _normalize_typed(kind, match.group(1))
            return _Candidate(rule.target_id, value, ExtractionMethod.LABEL, page)

        # Free text (names, addresses): clean the remainder and junk-filter it.
        if not allow_free_text:
            return None
        value = _clean_text(remainder)
        if not value:
            return None
        return _Candidate(rule.target_id, value, ExtractionMethod.LABEL, page)

    def _value_from_next_line(
        self,
        rule: SchemaFieldRule,
        lines: list[str],
        index: int,
        page: OCRPage,
        compiled: list[tuple[SchemaFieldRule, list[re.Pattern[str]]]],
    ) -> _Candidate | None:
        """
        Caption-above-value fallback for ID-card layouts: when a label ends a
        line with nothing after it, the very next non-empty line may BE the
        value — but only if that line carries no label of its own (otherwise
        it's just the next caption of a blank form).
        """
        for next_line in lines[index + 1 : index + 3]:
            stripped = next_line.strip()
            if not stripped:
                continue
            if len(stripped) > _MAX_FORM_LINE_CHARS:
                return None
            if self._segment_line(next_line, compiled):
                return None  # the next line is another caption, not a value
            return self._value_from_remainder(
                rule, next_line, page, allow_free_text=True
            )
        return None

    def _document_wide_value(
        self, rule: SchemaFieldRule, page: OCRPage
    ) -> _Candidate | None:
        """Label-less extraction for rules the schema marked `document_wide`."""
        kind = self._value_kind(rule)
        if kind == "choice":
            # Safe only when exactly ONE option word appears on the whole page
            # (e.g. "MALE" on an Aadhaar card; a form listing both is skipped).
            if rule.canonical is None:
                return None
            matched = self._match_single_option(rule.canonical, page.text)
            if matched is None:
                return None
            return _Candidate(rule.target_id, matched, ExtractionMethod.OPTION, page)
        pattern = _VALUE_PATTERNS.get(kind)
        if pattern is None:
            return None  # free text is never safe without a label
        match = pattern.search(page.text)
        if not match:
            return None
        value = _normalize_typed(kind, match.group(1))
        return _Candidate(rule.target_id, value, ExtractionMethod.PATTERN, page)

    def _match_single_option(self, canonical_id: str, text: str) -> str | None:
        """Exactly one schema option present -> its machine value; else None."""
        field = self._canonical.session_field(canonical_id)
        if field is None or not field.options:
            return None
        matched = {
            option.value
            for option in field.options
            if re.search(rf"\b{re.escape(option.label)}\b", text, re.IGNORECASE)
            or re.search(rf"\b{re.escape(option.value)}\b", text, re.IGNORECASE)
        }
        if len(matched) != 1:
            return None
        return matched.pop()

    # ------------------------------------------------------------------ #
    # Scoring + validation — reuses the existing engines, nothing new.
    # ------------------------------------------------------------------ #

    def _score_and_validate(self, candidate: _Candidate, document_id: str) -> CanonicalValue:
        session_field = self._canonical.session_field(candidate.canonical_id)
        if session_field is not None:
            validation = self._validation.validate_field(session_field, candidate.value)
        else:  # profile-only field with no session mapping: presence is enough
            validation = ValidationResult.ok("No session mapping — value accepted as-is.")
        confidence, _ = self._confidence.score(
            page_confidence=candidate.page.confidence,
            source=candidate.page.source,
            method=candidate.method,
            validation=validation,
            value=candidate.value,
        )
        return CanonicalValue(
            canonical_id=candidate.canonical_id,
            value=candidate.value,
            confidence=confidence,
            valid=validation.valid,
            validation_message=validation.message,
            method=candidate.method,
            source=candidate.page.source,
            page_number=candidate.page.page_number,
            document_id=document_id,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _value_kind(self, rule: SchemaFieldRule) -> str:
        """Rule override first, then the canonical field's declared kind."""
        if rule.value_kind:
            return rule.value_kind
        canonical = self._canonical.get(rule.canonical) if rule.canonical else None
        return canonical.value_kind if canonical else "text"

    def _compiled_rules(
        self, schema: DocumentSchema
    ) -> list[tuple[SchemaFieldRule, list[re.Pattern[str]]]]:
        cached = self._label_cache.get(schema.id)
        if cached is not None:
            return cached
        compiled = [
            (rule, [fuzzy_phrase_regex(label) for label in rule.labels])
            for rule in schema.fields
        ]
        self._label_cache[schema.id] = compiled
        return compiled

    def _header_regexes(self, schema: DocumentSchema) -> list[re.Pattern[str]]:
        cached = self._header_cache.get(schema.id)
        if cached is not None:
            return cached
        compiled = [fuzzy_phrase_regex(p) for p in schema.markers.strong]
        self._header_cache[schema.id] = compiled
        return compiled


# --------------------------------------------------------------------------- #
# Pure value-normalization helpers
# --------------------------------------------------------------------------- #


def _normalize_typed(kind: str, raw: str) -> str:
    """Canonicalize typed values (digits squeezed, PAN uppercased, dates dashed)."""
    if kind == "aadhaar":
        return re.sub(r"[ -]", "", raw)
    if kind == "pan":
        return raw.upper()
    if kind == "date":
        return re.sub(r"[/.]", "-", raw.strip())
    if kind == "number":
        return raw.replace(",", "")
    if kind in ("passport_no", "epic", "ifsc"):
        return raw.upper()
    return raw.strip()


def _clean_text(raw: str) -> str:
    """
    Reduce a free-text remainder to a plausible user value: drops printed
    instructions, form-box artifacts, boilerplate, and caption echoes.
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
        # Official documents print user data in BLOCK LETTERS; a remainder
        # starting lowercase is almost always the tail of a printed sentence.
        return ""
    if value.lower() in _CAPTION_VALUES:
        return ""
    return value


# Stateless singleton.
field_mapper = FieldMapper()
