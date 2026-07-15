"""
Domain models.

Strongly-typed Pydantic v2 models describing the *structure* of a KYC form:
fields, the options a choice-field offers, sections, and the whole form. These
are immutable reference data — once built by the registry they never change at
runtime, so they're declared `frozen=True`.

Runtime/session models (SessionProgress, InterviewState) are also defined here
so the whole domain vocabulary lives in one place; they're consumed from Phase 5
onward but belong to the domain today.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    FieldStatus,
    FieldType,
    InterviewStatus,
    SectionType,
    ValidationType,
)


class FieldOption(BaseModel):
    """
    A single selectable option for a choice field (SINGLE_CHOICE / MULTI_CHOICE).

    `value` is the stable machine value stored/validated; `label` is the
    human-facing text shown in the UI (e.g. value="1-5L", label="₹1–5 Lakh").
    """

    model_config = ConfigDict(frozen=True)

    value: str = Field(..., description="Stable machine value for this option.")
    label: str = Field(..., description="Human-readable label shown to the user.")


class KYCField(BaseModel):
    """
    A single field on the KYC form and all metadata needed to ask for, explain,
    validate, and later render it.

    This is the atomic unit of the entire application: the interview asks for one
    KYCField at a time, validation applies `validation_type`, and PDF generation
    maps `id` to a coordinate. Nothing downstream should invent fields — they all
    come from here via the registry.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique, stable field identifier (snake_case).")
    display_name: str = Field(..., description="Human-facing field name.")
    section: SectionType = Field(..., description="Section this field belongs to.")
    field_type: FieldType = Field(..., description="Input type driving UI + handling.")
    required: bool = Field(default=False, description="Whether the field is mandatory.")
    placeholder: str | None = Field(default=None, description="Short input hint.")
    help_text: str | None = Field(
        default=None, description="Plain-language explanation of the field."
    )
    validation_type: ValidationType = Field(
        default=ValidationType.NONE, description="Deterministic rule to apply (Phase 4)."
    )
    example: str | None = Field(default=None, description="Example of a valid value.")
    options: tuple[FieldOption, ...] = Field(
        default_factory=tuple,
        description="Allowed options for choice fields; empty for free-input fields.",
    )


class KYCSection(BaseModel):
    """
    A named section grouping related fields, mirroring the printed form layout
    (Identity / Address / Other / Declaration).
    """

    model_config = ConfigDict(frozen=True)

    id: SectionType = Field(..., description="Section identifier.")
    title: str = Field(..., description="Human-facing section title.")
    description: str | None = Field(default=None, description="What this section covers.")
    order: int = Field(..., description="Display order of the section on the form.")
    fields: tuple[KYCField, ...] = Field(
        default_factory=tuple, description="Fields belonging to this section, in order."
    )


class KYCForm(BaseModel):
    """
    The complete KYC form: identifying metadata plus its ordered sections. This
    is the top-level object the registry builds and the API exposes at /schema.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Stable form identifier.")
    title: str = Field(..., description="Official form title.")
    description: str | None = Field(default=None, description="What the form is for.")
    version: str = Field(..., description="Schema version of this form definition.")
    sections: tuple[KYCSection, ...] = Field(
        default_factory=tuple, description="Ordered sections making up the form."
    )


# --------------------------------------------------------------------------- #
# Runtime / session models (consumed from Phase 5; defined here for a single
# unified domain vocabulary).
# --------------------------------------------------------------------------- #


class SessionProgress(BaseModel):
    """Progress summary over a session: how many required fields are complete."""

    total_fields: int = Field(..., description="Total number of fields in the form.")
    required_fields: int = Field(..., description="Number of required fields.")
    completed_fields: int = Field(..., description="Required fields that are valid.")

    @property
    def is_complete(self) -> bool:
        """True when every required field has been validly completed."""
        return self.completed_fields >= self.required_fields


class FieldState(BaseModel):
    """The runtime status and current value of one field within a session."""

    field_id: str = Field(..., description="Identifier of the field this state tracks.")
    status: FieldStatus = Field(
        default=FieldStatus.PENDING, description="Current status of the field."
    )
    value: str | None = Field(default=None, description="User-provided value, if any.")
    error: str | None = Field(default=None, description="Validation error, if invalid.")


class InterviewState(BaseModel):
    """
    Full runtime state of an interview session: which form, overall status, the
    current field being asked, and per-field state. Owned by Phase 5's session
    service; modeled here so the domain defines the shape.
    """

    session_id: str = Field(..., description="Unique session identifier.")
    form_id: str = Field(..., description="Form being filled in this session.")
    status: InterviewStatus = Field(
        default=InterviewStatus.NOT_STARTED, description="Overall session status."
    )
    current_field_id: str | None = Field(
        default=None, description="Field currently being asked, if any."
    )
    fields: dict[str, FieldState] = Field(
        default_factory=dict, description="Per-field runtime state keyed by field id."
    )
