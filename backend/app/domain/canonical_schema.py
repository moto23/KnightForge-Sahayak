"""
Canonical KYC schema (Phase 11) — the ONE profile every document maps into.

Universal Document Intelligence rule: there is exactly one canonical KYC
model. A CVL form, an SBI form, a PAN card and an Aadhaar card all extract
into THESE fields — never into per-bank or per-document schemas. Document
schema JSON files (backend/schemas/*.json) map their printed labels onto
these canonical ids; this module is the registry those mappings target.

Each canonical field also declares which existing interview-session field it
feeds (`session_field_id`), so the unified profile flows into the untouched
Phase 5 interview / Phase 8 PDF machinery through the normal answer path.

Pure domain code: no I/O, no framework imports.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.kyc_schema import kyc_registry
from app.domain.models import KYCField


class CanonicalField(BaseModel):
    """One field of the canonical KYC profile."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Stable canonical field id (e.g. 'name', 'pan').")
    label: str = Field(..., description="Human-readable name for UI display.")
    session_field_id: str | None = Field(
        default=None,
        description=(
            "The interview-session (CVL registry) field this canonical field "
            "feeds. None = profile-only, never written into a session."
        ),
    )
    value_kind: str = Field(
        default="text",
        description=(
            "How values for this field are matched and normalized: "
            "text | name | date | pan | aadhaar | mobile | email | pincode | "
            "choice | number."
        ),
    )


# --------------------------------------------------------------------------- #
# THE canonical KYC profile — one model, every supported document maps into it.
# --------------------------------------------------------------------------- #

_CANONICAL_FIELDS: tuple[CanonicalField, ...] = (
    CanonicalField(id="name", label="Full Name", session_field_id="full_name", value_kind="name"),
    CanonicalField(id="father_name", label="Father's / Spouse's Name", session_field_id="father_spouse_name", value_kind="name"),
    CanonicalField(id="dob", label="Date of Birth", session_field_id="date_of_birth", value_kind="date"),
    CanonicalField(id="gender", label="Gender", session_field_id="gender", value_kind="choice"),
    CanonicalField(id="pan", label="PAN", session_field_id="pan", value_kind="pan"),
    CanonicalField(id="aadhaar", label="Aadhaar Number", session_field_id="aadhaar", value_kind="aadhaar"),
    CanonicalField(id="mobile", label="Mobile Number", session_field_id="mobile", value_kind="mobile"),
    CanonicalField(id="email", label="Email ID", session_field_id="email", value_kind="email"),
    CanonicalField(id="address", label="Address", session_field_id="correspondence_address", value_kind="text"),
    CanonicalField(id="city", label="City", session_field_id="city", value_kind="text"),
    CanonicalField(id="state", label="State", session_field_id="state", value_kind="text"),
    CanonicalField(id="pincode", label="PIN Code", session_field_id="pincode", value_kind="pincode"),
    CanonicalField(id="occupation", label="Occupation", session_field_id="occupation", value_kind="choice"),
    CanonicalField(id="income", label="Gross Annual Income", session_field_id="gross_annual_income", value_kind="choice"),
    CanonicalField(id="nationality", label="Nationality", session_field_id="nationality", value_kind="choice"),
)


class CanonicalSchemaRegistry:
    """
    Read-only registry over the canonical profile definition.

    Mirrors the KYCSchemaRegistry pattern: indexes built once, typed accessors,
    and every consumer (classifier, mapper, merge engine, DTOs) goes through
    this class — never through the private tuple above.
    """

    def __init__(self, fields: tuple[CanonicalField, ...] = _CANONICAL_FIELDS) -> None:
        self._fields_by_id: dict[str, CanonicalField] = {}
        for field in fields:
            if field.id in self._fields_by_id:
                raise ValueError(f"Duplicate canonical field id: {field.id!r}")
            self._fields_by_id[field.id] = field

    def all_fields(self) -> tuple[CanonicalField, ...]:
        """Every canonical field, in profile order."""
        return tuple(self._fields_by_id.values())

    def get(self, canonical_id: str) -> CanonicalField | None:
        """Look up one canonical field by id; None if it doesn't exist."""
        return self._fields_by_id.get(canonical_id)

    def session_field(self, canonical_id: str) -> KYCField | None:
        """
        The interview-session KYCField a canonical field feeds, or None.

        This is where the canonical profile plugs into the EXISTING schema
        registry — validation rules, options, and PDF coordinates all keep
        working because merged values travel through the same field ids.
        """
        canonical = self._fields_by_id.get(canonical_id)
        if canonical is None or canonical.session_field_id is None:
            return None
        return kyc_registry.get_field(canonical.session_field_id)


# Singleton — built once at import; the single source of truth.
canonical_registry = CanonicalSchemaRegistry()
