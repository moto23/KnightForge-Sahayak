"""
ValidationEngine — schema-driven dispatch of deterministic validators.

The engine is the ONLY place that maps a field's declared `validation_type` to
a rule implementation, via a dispatch table (dict) — no if/else chains, and
routes/services never pick validators themselves.

Validating a field runs a short, fixed pipeline:
  1. required check    — empty + required  → fail; empty + optional → pass
  2. options check     — choice fields must use one of their schema options
  3. format rule       — the validator registered for the field's validation_type

The engine is pure domain code: it depends only on the schema models and the
rule functions, making the whole pipeline unit-testable without FastAPI.
"""

from collections.abc import Callable

from app.domain.enums import FieldType, ValidationType
from app.domain.models import KYCField
from app.domain.validators import rules
from app.domain.validators.result import ValidationResult

# Type alias for a rule: raw string in, typed result out.
Validator = Callable[[str], ValidationResult]

# --------------------------------------------------------------------------- #
# Dispatch table — THE single mapping from declared type to implementation.
# Adding a new rule = one enum member + one function + one line here.
# --------------------------------------------------------------------------- #

_VALIDATORS: dict[ValidationType, Validator] = {
    ValidationType.NONE: rules.validate_noop,
    ValidationType.PAN: rules.validate_pan,
    ValidationType.AADHAAR: rules.validate_aadhaar,
    ValidationType.MOBILE: rules.validate_mobile,
    ValidationType.EMAIL: rules.validate_email,
    ValidationType.PINCODE: rules.validate_pincode,
    ValidationType.DATE: rules.validate_date,
    ValidationType.DOB: rules.validate_dob,
    ValidationType.NAME: rules.validate_name,
    ValidationType.NUMBER: rules.validate_number,
}

# Boolean fields accept these canonical string values.
_BOOLEAN_VALUES = {"yes", "no", "true", "false"}


class ValidationEngine:
    """Applies the correct deterministic rules to a KYC field's value."""

    def __init__(self, validators: dict[ValidationType, Validator] | None = None) -> None:
        # Injectable table so tests can stub rules; defaults to the real one.
        self._validators = validators or _VALIDATORS

    def validator_for(self, validation_type: ValidationType) -> Validator:
        """Return the rule registered for a validation type (noop if missing)."""
        return self._validators.get(validation_type, rules.validate_noop)

    def validate_field(self, field: KYCField, value: str | None) -> ValidationResult:
        """
        Validate one raw value against one schema field.

        Runs required → options → format, returning the FIRST failure so users
        see the most fundamental problem first.
        """
        raw = (value or "").strip()

        # 1. Required check.
        if not raw:
            if field.required:
                return ValidationResult.fail(
                    "required", f"{field.display_name} is required."
                )
            return ValidationResult.ok(
                f"{field.display_name} is optional and was left blank.", code="valid_empty"
            )

        # 2. Choice fields: the value must be one of the schema-defined options
        #    (accepts either the machine value or the human label).
        if field.options:
            allowed = {o.value.lower() for o in field.options} | {
                o.label.lower() for o in field.options
            }
            if raw.lower() not in allowed:
                choices = ", ".join(o.label for o in field.options)
                return ValidationResult.fail(
                    "invalid_option",
                    f"'{raw}' is not a valid choice for {field.display_name}. Options: {choices}.",
                )

        # 3. Boolean fields: accept canonical yes/no/true/false.
        if field.field_type == FieldType.BOOLEAN and raw.lower() not in _BOOLEAN_VALUES:
            return ValidationResult.fail(
                "invalid_boolean",
                f"{field.display_name} must be Yes or No.",
            )

        # 4. Format rule declared in the schema.
        return self.validator_for(field.validation_type)(raw)


# Stateless singleton — safe to share.
validation_engine = ValidationEngine()
