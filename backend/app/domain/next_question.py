"""
Next Question Engine — decides what to ask next, driven purely by the schema.

The engine walks the KYC Schema Registry in FORM ORDER (sections, then fields
as they appear on the printed form) and returns the first REQUIRED field that
does not yet have a valid answer. Nothing here hardcodes field names or order —
add/remove/reorder fields in the registry and the interview adapts automatically.

Pure domain logic: no I/O, no HTTP, trivially unit-testable
(next_required_field({}) -> first required field of the form).
"""

from collections.abc import Mapping

from app.domain.kyc_schema import KYCSchemaRegistry, kyc_registry
from app.domain.models import KYCField


class NextQuestionEngine:
    """Selects the next question from the schema given the answers so far."""

    def __init__(self, registry: KYCSchemaRegistry = kyc_registry) -> None:
        # Registry injected (defaulting to the singleton) for testability.
        self._registry = registry

    def next_required_field(self, answers: Mapping[str, str]) -> KYCField | None:
        """
        Return the first required field (in form order) with no valid answer,
        or None when every required field is answered — i.e. the interview can
        complete.
        """
        for field in self._registry.required_fields():
            if field.id not in answers:
                return field
        return None

    def remaining_required_fields(
        self, answers: Mapping[str, str]
    ) -> tuple[KYCField, ...]:
        """All required fields (in form order) still missing a valid answer."""
        return tuple(
            field
            for field in self._registry.required_fields()
            if field.id not in answers
        )


# Stateless singleton — safe to share across requests.
next_question_engine = NextQuestionEngine()
