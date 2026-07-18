"""
ConflictService (Phase 11) — surface disagreements; never silently overwrite.

When two documents claim different values for the same canonical field
("Prasad Nathe" on the PAN card vs "Prasad N. Nathe" on the passport), the
merge engine reports the field as disputed and THIS service:

    detect()  — turns disputed candidates into typed FieldConflicts, honoring
                resolutions the user already made (a resolved conflict is
                promoted back into the merged profile)
    resolve() — records the user's choice, validating that the chosen value
                really is one of the candidates (no invented values)

A disputed field is NEVER auto-applied to the interview session: it stays
pending — and is therefore asked about or resolved explicitly — until the
user chooses. That is the "please choose the correct value" contract.
"""

import logging

from app.core.exceptions import ConflictNotFoundError, InvalidConflictResolutionError
from app.domain.intelligence import ConflictOption, FieldConflict, MergedField, ProfileState

logger = logging.getLogger(__name__)


class ConflictService:
    """Detect field conflicts and record user resolutions."""

    def detect(
        self,
        disputed: dict[str, tuple[ConflictOption, ...]],
        resolutions: dict[str, str],
    ) -> tuple[tuple[MergedField, ...], tuple[FieldConflict, ...]]:
        """
        Build FieldConflicts from disputed candidates.

        A dispute whose canonical field has a stored user resolution matching
        one of the current candidates is returned RESOLVED, and the chosen
        value is promoted into the merged profile. A stored resolution whose
        value no longer exists among candidates (its source document was
        deleted) is ignored — the conflict reopens honestly.
        """
        promoted: list[MergedField] = []
        conflicts: list[FieldConflict] = []
        for canonical_id, options in disputed.items():
            chosen = self._matching_option(options, resolutions.get(canonical_id))
            if chosen is not None:
                promoted.append(
                    MergedField(
                        canonical_id=canonical_id,
                        value=chosen.value,
                        source_document_id=chosen.document_id,
                        confidence=chosen.confidence,
                        validated=chosen.valid,
                        resolved=True,
                    )
                )
            conflicts.append(
                FieldConflict(
                    canonical_id=canonical_id,
                    options=options,
                    resolved=chosen is not None,
                    resolved_value=chosen.value if chosen is not None else None,
                )
            )
        return tuple(promoted), tuple(conflicts)

    def resolve(
        self,
        state: ProfileState,
        conflicts: tuple[FieldConflict, ...],
        canonical_id: str,
        document_id: str | None = None,
        value: str | None = None,
    ) -> str:
        """
        Record the user's choice for one conflicted field and return the
        chosen value. The choice must name one of the candidates — either by
        source document or by exact value; anything else is a typed 422.
        """
        conflict = next(
            (c for c in conflicts if c.canonical_id == canonical_id), None
        )
        if conflict is None:
            raise ConflictNotFoundError(canonical_id)

        chosen: ConflictOption | None = None
        if document_id is not None:
            chosen = next(
                (o for o in conflict.options if o.document_id == document_id), None
            )
            if chosen is None:
                raise InvalidConflictResolutionError(
                    f"document '{document_id}' offers no value for '{canonical_id}'."
                )
        elif value is not None:
            wanted = value.strip()
            chosen = next(
                (o for o in conflict.options if o.value.strip() == wanted), None
            )
            if chosen is None:
                raise InvalidConflictResolutionError(
                    f"'{wanted}' is not one of the candidate values for '{canonical_id}'."
                )
        else:
            raise InvalidConflictResolutionError(
                "provide either 'document_id' or 'value' to choose a candidate."
            )

        state.resolutions[canonical_id] = chosen.value
        logger.info(
            "Conflict on '%s' resolved for session %s: %r (from document %s)",
            canonical_id,
            state.session_id,
            chosen.value,
            chosen.document_id,
        )
        return chosen.value

    @staticmethod
    def _matching_option(
        options: tuple[ConflictOption, ...], resolution: str | None
    ) -> ConflictOption | None:
        if resolution is None:
            return None
        return next((o for o in options if o.value == resolution), None)


# Stateless singleton.
conflict_service = ConflictService()
