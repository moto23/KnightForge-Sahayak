"""
Schema endpoints — expose the KYC form definition to clients.

These are read-only endpoints over the schema registry (via FormService). The
future frontend uses them to render sections/fields; nothing here ever mutates
state.

Route-ordering note: the static paths `/schema/sections` and `/schema/required`
are declared BEFORE the dynamic `/schema/{field_id}`, otherwise FastAPI would
treat "sections" and "required" as field ids.
"""

import logging

from fastapi import APIRouter, Depends

from app.core.dependencies import get_form_service
from app.schemas.form import (
    FieldListResponse,
    FieldResponse,
    FormSchemaResponse,
    SectionListResponse,
)
from app.services.form_service import FormService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schema", tags=["Form Schema"])


@router.get(
    "",
    response_model=FormSchemaResponse,
    summary="Get the complete KYC form schema",
    description="The full form definition: metadata, sections, and every field.",
)
async def get_schema(
    service: FormService = Depends(get_form_service),
) -> FormSchemaResponse:
    """Return the entire form definition — the frontend's bootstrap call."""
    form = service.get_form()
    return FormSchemaResponse(form=form, total_fields=len(service.get_all_fields()))


@router.get(
    "/sections",
    response_model=SectionListResponse,
    summary="List form sections",
    description="All sections of the KYC form in display order, with their fields.",
)
async def get_sections(
    service: FormService = Depends(get_form_service),
) -> SectionListResponse:
    """Return the ordered sections of the form."""
    sections = list(service.get_sections())
    return SectionListResponse(sections=sections, count=len(sections))


@router.get(
    "/required",
    response_model=FieldListResponse,
    summary="List required fields",
    description="Only the mandatory fields — the interview's minimum checklist.",
)
async def get_required_fields(
    service: FormService = Depends(get_form_service),
) -> FieldListResponse:
    """Return only the fields that must be completed for a valid submission."""
    fields = list(service.get_required_fields())
    return FieldListResponse(fields=fields, count=len(fields))


@router.get(
    "/{field_id}",
    response_model=FieldResponse,
    summary="Get a single field",
    description="Full metadata for one field, looked up by its stable id.",
    responses={404: {"description": "Field id not found in the KYC schema."}},
)
async def get_field(
    field_id: str,
    service: FormService = Depends(get_form_service),
) -> FieldResponse:
    """Return one field by id; 404s via KYCFieldNotFoundError if unknown."""
    return service.get_field(field_id)
