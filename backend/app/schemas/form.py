"""
API response schemas for the schema/form endpoints.

These are the typed response envelopes the API returns. The domain models
(KYCForm, KYCSection, KYCField) are already strongly-typed Pydantic models and
serve directly as the payload types — these wrappers add list envelopes and
counts so responses are self-describing rather than bare arrays.

No endpoint returns a raw dict; every response is one of these typed models.
"""

from pydantic import BaseModel, Field

from app.domain.models import KYCField, KYCForm, KYCSection


class FormSchemaResponse(BaseModel):
    """Full form definition returned by GET /schema."""

    form: KYCForm = Field(..., description="Complete KYC form definition.")
    total_fields: int = Field(..., description="Total number of fields in the form.")


class SectionListResponse(BaseModel):
    """List of sections returned by GET /schema/sections."""

    sections: list[KYCSection] = Field(..., description="All form sections in order.")
    count: int = Field(..., description="Number of sections.")


class FieldListResponse(BaseModel):
    """List of fields returned by GET /schema/required (and reusable elsewhere)."""

    fields: list[KYCField] = Field(..., description="The requested fields, in form order.")
    count: int = Field(..., description="Number of fields returned.")


# A single field is returned using the domain KYCField model directly, since it
# is already a complete, typed representation — no wrapper needed.
FieldResponse = KYCField
