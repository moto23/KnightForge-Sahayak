"""
API request/response schemas for the validation endpoints.

Typed DTOs for POST /validate (single field) and POST /validate/form (whole
form). Responses embed the domain ValidationResult directly — it's already a
strongly-typed Pydantic model and IS the contract for a validation outcome.
"""

from pydantic import BaseModel, Field

from app.domain.validators.result import ValidationResult


class ValidateFieldRequest(BaseModel):
    """Request body for validating one field's value."""

    field_id: str = Field(
        ..., description="Stable id of the KYC field to validate.", examples=["pan"]
    )
    value: str | None = Field(
        default=None, description="The raw user value.", examples=["ABCDE1234F"]
    )


class ValidateFieldResponse(BaseModel):
    """Outcome of validating one field."""

    field_id: str = Field(..., description="The field that was validated.")
    result: ValidationResult = Field(..., description="Validation outcome.")


class ValidateFormRequest(BaseModel):
    """
    Request body for validating a whole form.

    `values` maps field id → raw user value. Required fields missing from the
    map are still checked (and fail with code 'required'); unknown ids are
    ignored.
    """

    values: dict[str, str | None] = Field(
        ...,
        description="Map of field id to raw value.",
        examples=[{"full_name": "Rahul Sharma", "pan": "ABCDE1234F"}],
    )


class FieldValidationItem(BaseModel):
    """One field's validation outcome inside a form-level response."""

    field_id: str = Field(..., description="The validated field.")
    result: ValidationResult = Field(..., description="Validation outcome.")


class ValidateFormResponse(BaseModel):
    """Aggregated outcome of validating an entire form submission."""

    valid: bool = Field(..., description="True only if every checked field passed.")
    checked: int = Field(..., description="Total fields validated.")
    error_count: int = Field(..., description="Number of failing fields.")
    errors: list[FieldValidationItem] = Field(
        ..., description="Only the failing fields, for quick client handling."
    )
    results: list[FieldValidationItem] = Field(
        ..., description="Every field checked, passing and failing."
    )
