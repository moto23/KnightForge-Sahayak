"""
Validation endpoints — deterministic checking of KYC field values.

Thin HTTP layer over FormValidationService. There is NO validation logic here
and no if/else selecting validators — the service and engine own all of that.
Everything is deterministic; no AI is involved.
"""

import logging

from fastapi import APIRouter, Depends

from app.core.dependencies import get_form_validation_service
from app.schemas.validation import (
    FieldValidationItem,
    ValidateFieldRequest,
    ValidateFieldResponse,
    ValidateFormRequest,
    ValidateFormResponse,
)
from app.services.form_validation_service import FormValidationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validate", tags=["Validation"])


@router.post(
    "",
    response_model=ValidateFieldResponse,
    summary="Validate a single field",
    description="Validate one field's value using its schema-declared rule.",
    responses={404: {"description": "Field id not found in the KYC schema."}},
)
async def validate_field(
    request: ValidateFieldRequest,
    service: FormValidationService = Depends(get_form_validation_service),
) -> ValidateFieldResponse:
    """Validate one value; 404 (typed envelope) if the field id is unknown."""
    result = service.validate_field(request.field_id, request.value)
    return ValidateFieldResponse(field_id=request.field_id, result=result)


@router.post(
    "/form",
    response_model=ValidateFormResponse,
    summary="Validate an entire form",
    description=(
        "Validate a whole submission. Every required field is checked (even if "
        "absent), plus any optional fields supplied. Returns all results and a "
        "convenient errors-only list."
    ),
)
async def validate_form(
    request: ValidateFormRequest,
    service: FormValidationService = Depends(get_form_validation_service),
) -> ValidateFormResponse:
    """Validate a full form; supports multiple simultaneous errors."""
    outcome = service.validate_form(request.values)
    results = [
        FieldValidationItem(field_id=fv.field_id, result=fv.result)
        for fv in outcome.results
    ]
    errors = [item for item in results if not item.result.valid]
    return ValidateFormResponse(
        valid=outcome.valid,
        checked=len(results),
        error_count=len(errors),
        errors=errors,
        results=results,
    )
