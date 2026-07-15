"""
FormValidationService — business-layer validation over KYC fields.

Bridges the API and the pure domain ValidationEngine: it resolves field ids
against the schema registry (via FormService), runs the engine, and aggregates
per-field results into a whole-form outcome. Holds no state and does no I/O.

Raises the typed KYCFieldNotFoundError (never an HTTP error) for unknown ids,
keeping this layer HTTP-agnostic.
"""

from dataclasses import dataclass

from app.core.exceptions import KYCFieldNotFoundError
from app.domain.models import KYCField
from app.domain.validators.engine import ValidationEngine, validation_engine
from app.domain.validators.result import ValidationResult
from app.services.form_service import FormService, form_service


@dataclass(frozen=True)
class FieldValidation:
    """One field's id paired with its validation result (for form-level output)."""

    field_id: str
    result: ValidationResult


@dataclass(frozen=True)
class FormValidation:
    """Aggregated outcome of validating a set of fields."""

    valid: bool
    results: tuple[FieldValidation, ...]

    @property
    def errors(self) -> tuple[FieldValidation, ...]:
        """Only the failing field validations."""
        return tuple(fv for fv in self.results if not fv.result.valid)


class FormValidationService:
    """Validate single fields or whole forms using the domain engine."""

    def __init__(
        self,
        forms: FormService = form_service,
        engine: ValidationEngine = validation_engine,
    ) -> None:
        # Both collaborators injected (defaulting to singletons) for testability.
        self._forms = forms
        self._engine = engine

    def validate_field(self, field_id: str, value: str | None) -> ValidationResult:
        """
        Validate a single value for the field with the given id.

        Raises KYCFieldNotFoundError if the id is unknown.
        """
        field: KYCField = self._forms.get_field(field_id)  # raises if unknown
        return self._engine.validate_field(field, value)

    def validate_form(self, values: dict[str, str | None]) -> FormValidation:
        """
        Validate a whole form's submitted values.

        Runs every REQUIRED field plus any optional fields the caller supplied,
        so missing required fields are reported even when absent from `values`.
        Unknown keys in `values` are ignored (they don't exist on the form).
        """
        results: list[FieldValidation] = []

        # Fields to check: all required fields, union the provided keys that
        # correspond to real fields.
        required_ids = {f.id for f in self._forms.get_required_fields()}
        provided_ids = {k for k in values if self._forms_has(k)}
        for field_id in sorted(required_ids | provided_ids):
            field = self._forms.get_field(field_id)
            result = self._engine.validate_field(field, values.get(field_id))
            results.append(FieldValidation(field_id=field_id, result=result))

        all_valid = all(fv.result.valid for fv in results)
        return FormValidation(valid=all_valid, results=tuple(results))

    def _forms_has(self, field_id: str) -> bool:
        """True if the id corresponds to a real form field."""
        try:
            self._forms.get_field(field_id)
            return True
        except KYCFieldNotFoundError:
            return False


# Stateless singleton.
form_validation_service = FormValidationService()
