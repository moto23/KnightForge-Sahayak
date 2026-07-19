"""
MergeService (Phase 11) — fuse per-document extractions into ONE profile.

Multi-Document Intelligence core: a PAN card contributes name + PAN, Aadhaar
contributes DOB + address, a passport contributes nationality — this service
merges them all into the single canonical KYC profile.

Merge priority (per canonical field, best evidence first):

    1. validated value        — a value the Validation Engine accepted
    2. higher OCR confidence  — cleaner reads outrank noisy ones
    3. earlier upload         — first-seen wins ties (stable, predictable)

Values are compared through a per-kind normalization ("ABCDE1234F" ==
"abcde1234f", "15/08/1999" == "15-08-1999", "9876 5432 1098" == aadhaar
digits) so formatting noise never manufactures a conflict. Values that are
GENUINELY different ("Prasad Nathe" vs "Prasad N. Nathe") are NEVER silently
merged — they come back as disputed fields for the ConflictService to surface.
"""

import logging
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime

from app.domain.canonical_schema import CanonicalSchemaRegistry, canonical_registry
from app.domain.intelligence import (
    CanonicalValue,
    ConflictOption,
    DocumentProfile,
    MergedField,
    ProfileState,
)

logger = logging.getLogger(__name__)

_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d")

# Kinds whose values are pure digit strings once normalized.
_DIGIT_KINDS = {"aadhaar", "mobile", "pincode", "number"}


@dataclass(frozen=True)
class MergeOutcome:
    """The merge engine's verdict: unanimous fields + disputed candidates."""

    merged: tuple[MergedField, ...]
    # canonical_id -> distinct candidate values, best evidence first.
    disputed: dict[str, tuple[ConflictOption, ...]] = dc_field(default_factory=dict)


class MergeService:
    """Combine every processed document's canonical values into one profile."""

    def __init__(self, canonical: CanonicalSchemaRegistry = canonical_registry) -> None:
        self._canonical = canonical

    def merge(self, state: ProfileState) -> MergeOutcome:
        """
        Recompute the unified profile from ALL of a session's documents.

        Pure recomputation — no caching — so adding or deleting a document can
        never leave stale merged values behind.
        """
        candidates = self._collect(state)
        merged: list[MergedField] = []
        disputed: dict[str, tuple[ConflictOption, ...]] = {}

        for canonical_id, ranked in candidates.items():
            groups = self._group_by_value(canonical_id, ranked)
            if len(groups) == 1:
                best = groups[0][0]
                merged.append(
                    MergedField(
                        canonical_id=canonical_id,
                        value=best.value,
                        source_document_id=best.document_id,
                        confidence=best.confidence,
                        validated=best.valid,
                    )
                )
            else:
                # Genuinely different values: never silently overwritten.
                disputed[canonical_id] = tuple(
                    ConflictOption(
                        document_id=group[0].document_id,
                        value=group[0].value,
                        confidence=group[0].confidence,
                        valid=group[0].valid,
                    )
                    for group in groups
                )

        logger.info(
            "Merge for session %s: %d documents -> %d merged fields, %d disputed",
            state.session_id,
            len(state.documents),
            len(merged),
            len(disputed),
        )
        return MergeOutcome(merged=tuple(merged), disputed=disputed)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _collect(self, state: ProfileState) -> dict[str, list[CanonicalValue]]:
        """
        Gather every document's values per canonical field, priority-ranked:
        validated first, then higher confidence, then earlier upload.
        """
        sequence_of: dict[str, int] = {
            doc.document_id: doc.sequence for doc in state.documents.values()
        }
        collected: dict[str, list[CanonicalValue]] = {}
        documents: list[DocumentProfile] = sorted(
            state.documents.values(), key=lambda d: d.sequence
        )
        for document in documents:
            for value in document.values:
                collected.setdefault(value.canonical_id, []).append(value)
        for values in collected.values():
            values.sort(
                key=lambda v: (
                    not v.valid,                       # 1. validated value
                    -v.confidence,                     # 2. higher OCR confidence
                    sequence_of.get(v.document_id, 0), # 3. earlier upload
                )
            )
        return collected

    def _group_by_value(
        self, canonical_id: str, ranked: list[CanonicalValue]
    ) -> list[list[CanonicalValue]]:
        """
        Group priority-ranked candidates by normalized value, preserving rank
        order both across groups and inside each group (so `groups[0][0]` is
        always the single best piece of evidence overall).
        """
        groups: dict[str, list[CanonicalValue]] = {}
        for value in ranked:
            key = self.comparison_key(canonical_id, value.value)
            groups.setdefault(key, []).append(value)
        return list(groups.values())

    def comparison_key(self, canonical_id: str, value: str) -> str:
        """
        Normalize a value for equality: formatting noise must never create a
        conflict, but real differences must never be papered over.
        """
        canonical = self._canonical.get(canonical_id)
        kind = canonical.value_kind if canonical else "text"
        raw = value.strip()

        if kind in _DIGIT_KINDS:
            return re.sub(r"\D", "", raw)
        if kind == "date":
            for fmt in _DATE_FORMATS:
                try:
                    return datetime.strptime(re.sub(r"[/.]", "-", raw), fmt).date().isoformat()
                except ValueError:
                    continue
            # Unparseable date: fall through to text normalization.
        # Text-ish kinds (and choice values): case/spacing/punctuation-blind.
        #
        # Punctuation is split into two classes, because collapsing both to a
        # space manufactured conflicts. A full stop or apostrophe sits INSIDE a
        # word — "M.G. Road" and "MG Road" are the same address, "O'Brien" and
        # "OBrien" the same name — so those are deleted. A comma, hyphen or
        # slash SEPARATES words — "Prasad-Nathe" is "Prasad Nathe" — so those
        # become spaces. Treating "M.G." as "m g" made it differ from "mg" and
        # raised a conflict over one address written two ways.
        key = re.sub(r"[.']", "", raw.casefold())
        key = re.sub(r"[,\-/]", " ", key)
        return re.sub(r"\s+", " ", key).strip()


# Stateless singleton.
merge_service = MergeService()
