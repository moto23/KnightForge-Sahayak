"""
DocumentClassifierService (Phase 11) — detect WHICH document was uploaded.

First stage of the Universal Document Intelligence pipeline: given a
document's raw OCR text, score every loaded DocumentSchema by its marker
phrases and pick the best match. The winning schema then drives the ONE
shared extraction pipeline (FieldMapper.extract_document) — the classifier is
the only component that decides *which* schema, never *how* to extract.

Scoring is deterministic and schema-driven:
    strong marker found -> +3 points  (issuer names: "state bank of india")
    weak marker found   -> +1 point   (generic words: "kyc", "application form")
A schema is a candidate only if it reaches its own `min_score`; the highest
score wins (strong hits, then schema id, break ties). No candidate ->
'unknown', which downstream falls back to the generic document-wide schema.
"""

import logging
import re

from app.domain.intelligence import ClassificationResult, DocumentSchema
from app.services.field_mapper import fuzzy_phrase_regex

logger = logging.getLogger(__name__)

_STRONG_POINTS = 3
_WEAK_POINTS = 1

# The generic fallback schema must never win classification.
_UNKNOWN_KIND = "unknown"

UNKNOWN_CLASSIFICATION = ClassificationResult(
    schema_id="unknown",
    label="Unknown Document",
    kind=_UNKNOWN_KIND,
    score=0,
    confidence=0.0,
    matched_markers=(),
)


class DocumentClassifierService:
    """Score OCR text against every schema's markers; return the best match."""

    def __init__(self) -> None:
        # Compiled marker regexes cached per schema id (schemas are frozen).
        self._marker_cache: dict[
            str,
            tuple[
                list[tuple[str, re.Pattern[str]]],
                list[tuple[str, re.Pattern[str]]],
                list[tuple[str, re.Pattern[str]]],
            ],
        ] = {}

    def classify(
        self, text: str, schemas: tuple[DocumentSchema, ...]
    ) -> ClassificationResult:
        """
        Detect the document type of `text` among the loaded schemas.

        Never raises: empty text or no reachable schema simply yields the
        'unknown' verdict, and the pipeline degrades to generic extraction.
        """
        if not text.strip():
            return UNKNOWN_CLASSIFICATION

        best: ClassificationResult | None = None
        best_key: tuple[int, int, str] | None = None
        for schema in schemas:
            if schema.kind == _UNKNOWN_KIND:
                continue  # the generic fallback never competes
            score, strong_hits, matched = self._score(text, schema)
            if score < schema.markers.min_score:
                continue
            # Deterministic ranking: score, then strong evidence, then id.
            key = (score, strong_hits, schema.id)
            if best_key is None or key > best_key:
                best_key = key
                best = ClassificationResult(
                    schema_id=schema.id,
                    label=schema.label,
                    kind=schema.kind,
                    score=score,
                    confidence=self._confidence(score, schema.markers.min_score),
                    matched_markers=tuple(matched),
                )

        if best is None:
            logger.info("Classification: no schema matched — unknown document")
            return UNKNOWN_CLASSIFICATION
        logger.info(
            "Classification: '%s' (score=%d, markers=%s)",
            best.schema_id,
            best.score,
            ", ".join(best.matched_markers),
        )
        return best

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _score(
        self, text: str, schema: DocumentSchema
    ) -> tuple[int, int, list[str]]:
        strong, weak, patterns = self._compiled_markers(schema)
        score = 0
        strong_hits = 0
        matched: list[str] = []
        for phrase, regex in strong:
            if regex.search(text):
                score += _STRONG_POINTS
                strong_hits += 1
                matched.append(phrase)
        for phrase, regex in weak:
            if regex.search(text):
                score += _WEAK_POINTS
                matched.append(phrase)
        # Format signatures: evidence from the VALUES themselves (an MRZ line,
        # a PAN-shaped token) — captions may be unreadable on a phone photo,
        # the data format usually is not.
        for pattern, regex in patterns:
            if regex.search(text):
                score += _STRONG_POINTS
                strong_hits += 1
                matched.append(f"format:{pattern}")
        return score, strong_hits, matched

    @staticmethod
    def _confidence(score: int, min_score: int) -> float:
        """Normalize the raw score: reaching min_score = 0.5, double it = 1.0."""
        ceiling = max(min_score * 2, 1)
        return round(min(1.0, score / ceiling), 2)

    def _compiled_markers(
        self, schema: DocumentSchema
    ) -> tuple[
        list[tuple[str, re.Pattern[str]]],
        list[tuple[str, re.Pattern[str]]],
        list[tuple[str, re.Pattern[str]]],
    ]:
        cached = self._marker_cache.get(schema.id)
        if cached is not None:
            return cached
        patterns: list[tuple[str, re.Pattern[str]]] = []
        for raw in schema.markers.patterns:
            try:
                patterns.append((raw, re.compile(raw, re.MULTILINE)))
            except re.error:  # a bad schema regex must never break uploads
                logger.warning("Schema '%s': invalid marker pattern %r", schema.id, raw)
        compiled = (
            [(phrase, fuzzy_phrase_regex(phrase)) for phrase in schema.markers.strong],
            [(phrase, fuzzy_phrase_regex(phrase)) for phrase in schema.markers.weak],
            patterns,
        )
        self._marker_cache[schema.id] = compiled
        return compiled


# Stateless singleton.
document_classifier = DocumentClassifierService()
