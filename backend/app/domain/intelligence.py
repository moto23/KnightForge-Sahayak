"""
Universal Document Intelligence domain models (Phase 11).

Every stage of the schema-driven pipeline speaks in these typed models:

    DocumentSchema        — one supported form/document, loaded from JSON
    ClassificationResult  — which schema an uploaded document matched
    CanonicalValue        — one canonical field's value from ONE document
    DocumentProfile       — everything one document contributed
    MergedField           — one canonical field after the merge engine
    ConflictOption        — one candidate value inside a conflict
    FieldConflict         — two documents disagree; the user must choose
    ProfileState          — the per-session accumulator the pipeline mutates

The pipeline is deliberately generic: NOTHING here names CVL, SBI, HDFC or
any other issuer. Adding a new form is a new JSON file — no Python changes.
Like the rest of the domain, this module has no I/O and no framework imports.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import ExtractionMethod, ExtractionSource
from app.domain.form_assets import FormAssetRequirements
from app.domain.session import utc_now

# --------------------------------------------------------------------------- #
# Document schemas (loaded from backend/schemas/*.json)
# --------------------------------------------------------------------------- #


class SchemaFieldRule(BaseModel):
    """
    How to find ONE field in ONE document type's text.

    A rule targets either a canonical KYC field (`canonical`) or, when the
    value has no place in the canonical profile (a passport number, an IFSC
    code), an EXTENDED-profile key (`extra_key` + `extra_label`). Extracted
    data is never discarded just because the KYC form doesn't ask for it —
    it lands in the document's extended profile instead.
    """

    model_config = ConfigDict(frozen=True)

    canonical: str | None = Field(
        default=None, description="Canonical field id this rule extracts into."
    )
    extra_key: str | None = Field(
        default=None,
        description="Extended-profile key for values outside the canonical model.",
    )
    extra_label: str | None = Field(
        default=None, description="Human-readable name for an extended field."
    )
    labels: tuple[str, ...] = Field(
        default=(),
        description="Printed captions/aliases for this field on this document.",
    )
    value_kind: str | None = Field(
        default=None,
        description=(
            "Override of the canonical field's value kind for this document "
            "(required for extended fields); None = use the canonical definition."
        ),
    )
    document_wide: bool = Field(
        default=False,
        description=(
            "True if the value's format is unambiguous enough to extract "
            "WITHOUT a printed label (a PAN on a PAN card, gender on Aadhaar)."
        ),
    )

    @model_validator(mode="after")
    def _canonical_or_extra(self) -> "SchemaFieldRule":
        if self.canonical is None and self.extra_key is None:
            raise ValueError("A field rule needs 'canonical' or 'extra_key'.")
        return self

    @property
    def target_id(self) -> str:
        """Unique extraction target: canonical id, or a namespaced extra key."""
        return self.canonical if self.canonical is not None else f"extra.{self.extra_key}"

    @property
    def is_extra(self) -> bool:
        return self.canonical is None


class SchemaMarkers(BaseModel):
    """Classification evidence: phrases that identify this document type."""

    model_config = ConfigDict(frozen=True)

    strong: tuple[str, ...] = Field(
        default=(), description="Near-unique phrases (issuer names) — 3 points each."
    )
    weak: tuple[str, ...] = Field(
        default=(), description="Supporting phrases (generic form words) — 1 point each."
    )
    patterns: tuple[str, ...] = Field(
        default=(),
        description=(
            "Regex FORMAT signatures — 3 points each. Evidence from the "
            "values themselves (an MRZ line, a PAN-shaped token, an IFSC "
            "code), so a photo with no readable captions still classifies."
        ),
    )
    min_score: int = Field(
        default=3, description="Minimum marker score required to claim a match."
    )


class SchemaConditionalRule(BaseModel):
    """A form's declaration that one field matters only in certain states."""

    model_config = ConfigDict(frozen=True)

    field_id: str = Field(..., description="Interview field this rule can require.")
    when_field: str = Field(..., description="Interview field whose state is read.")
    equals: tuple[str, ...] = Field(
        default=(), description="Values of when_field that trigger the requirement."
    )
    unless_answered: bool = Field(
        default=False, description="Require only while when_field is unanswered."
    )


class DocumentSchema(BaseModel):
    """One supported document type — the unit the whole pipeline is driven by."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Stable schema id (e.g. 'sbi_kyc', 'pan_card').")
    label: str = Field(..., description="Human-readable document name for badges/UI.")
    kind: str = Field(
        ..., description="kyc_form | identity_document | unknown (generic fallback)."
    )
    markers: SchemaMarkers = Field(
        default_factory=SchemaMarkers, description="Classification markers."
    )
    fields: tuple[SchemaFieldRule, ...] = Field(
        default=(), description="Label -> canonical field mapping rules."
    )
    required_canonical: tuple[str, ...] = Field(
        default=(),
        description=(
            "Canonical field ids THIS form marks mandatory (Phase 13). When "
            "the form is chosen as the session's primary form, this set drives "
            "progress, completion and which questions the interview asks — so "
            "each bank's form is measured against its own requirements. Empty "
            "= fall back to the interview registry's default required set."
        ),
    )
    conditional_required: tuple["SchemaConditionalRule", ...] = Field(
        default=(),
        description=(
            "Fields this form requires only in certain states (Phase 14) — "
            "PAN-exempt proof of identity, 'other' free-text companions. Data "
            "only, so an unseen form declares its own conditions in JSON."
        ),
    )
    required_session_fields: tuple[str, ...] = Field(
        default=(),
        description=(
            "Interview field ids this form requires that have NO canonical "
            "home (marital status, residential status, PEP…). Unioned with "
            "required_canonical so form-specific mandatory fields are still "
            "asked, counted and printed."
        ),
    )
    never_prefill: tuple[str, ...] = Field(
        default=(),
        description=(
            "Canonical field ids that must ALWAYS be asked rather than "
            "auto-filled from this form, however confidently they extract.\n\n"
            "Some values read cleanly and are still wrong, because the label "
            "the extractor anchors on belongs to something else on the page. "
            "SBI's letterhead says 'STATE BANK OF INDIA', so 'State' captured "
            "'BANK OF INDIA'; its office-use block yielded a bank-internal "
            "address as the customer's email. Both passed validation, so no "
            "confidence threshold could catch them - the only safe answer is "
            "to ask the person. The value is still EXTRACTED and shown in the "
            "profile as evidence; it simply never becomes an answer by itself."
        ),
    )
    requires_photo: bool = Field(
        default=False,
        description=(
            "This form prints a photograph box. A DECLARATION, not a detection: "
            "used when the user only SELECTED the form (nothing to inspect) and "
            "as a floor when the uploaded PDF is scanned/flat and the caption "
            "could not be located. False here never suppresses a photo box that "
            "was actually found in the document."
        ),
    )
    requires_signature: bool = Field(
        default=False,
        description="This form prints a signature line. Same semantics as requires_photo.",
    )


class SchemaSource(ABC):
    """
    Port for loading document schemas. The concrete adapter (filesystem JSON
    today, a DB tomorrow) lives in app/infrastructure/ — services never read
    files themselves.
    """

    @abstractmethod
    def load_all(self) -> tuple[DocumentSchema, ...]:
        """Every valid schema available, in a stable order."""


# --------------------------------------------------------------------------- #
# Classification + extraction
# --------------------------------------------------------------------------- #


class ClassificationResult(BaseModel):
    """The document classifier's verdict for one uploaded document."""

    model_config = ConfigDict(frozen=True)

    schema_id: str = Field(..., description="Matched schema id, or 'unknown'.")
    label: str = Field(..., description="Human-readable document type.")
    kind: str = Field(..., description="kyc_form | identity_document | unknown.")
    score: int = Field(default=0, description="Raw marker score achieved.")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Normalized classification confidence."
    )
    matched_markers: tuple[str, ...] = Field(
        default=(), description="The marker phrases that were actually found."
    )


class CanonicalValue(BaseModel):
    """One canonical field's value as extracted from ONE document."""

    model_config = ConfigDict(frozen=True)

    canonical_id: str = Field(..., description="Canonical profile field id.")
    value: str = Field(..., description="The normalized extracted value.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence.")
    valid: bool = Field(..., description="Validation Engine verdict on the value.")
    validation_message: str = Field(default="", description="Why validation passed/failed.")
    method: ExtractionMethod = Field(..., description="How the value was matched.")
    source: ExtractionSource = Field(..., description="pdf_text_layer or ocr.")
    page_number: int = Field(..., ge=1, description="Page the value was found on.")
    document_id: str = Field(..., description="Id of the source document.")


class ExtraValue(BaseModel):
    """
    One EXTENDED-profile value: real data read from a document that has no
    canonical KYC home (passport number, IFSC, EPIC number…). Kept — never
    discarded — with full provenance, as supporting evidence.
    """

    model_config = ConfigDict(frozen=True)

    key: str = Field(..., description="Stable extended-profile key (e.g. 'passport_number').")
    label: str = Field(..., description="Human-readable field name for the UI.")
    value: str = Field(..., description="The normalized extracted value.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence.")
    method: ExtractionMethod = Field(..., description="How the value was matched.")
    source: ExtractionSource = Field(..., description="pdf_text_layer or ocr.")
    page_number: int = Field(..., ge=1, description="Page the value was found on.")
    document_id: str = Field(..., description="Id of the source document.")


class DocumentProfile(BaseModel):
    """Everything ONE document contributed to a session's unified profile."""

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(..., description="Uploaded document id.")
    filename: str = Field(..., description="Original filename (display only).")
    sequence: int = Field(..., ge=1, description="Upload order — earlier wins merge ties.")
    classification: ClassificationResult = Field(..., description="Detected document type.")
    values: tuple[CanonicalValue, ...] = Field(
        default=(), description="Canonical values extracted from this document."
    )
    extras: tuple[ExtraValue, ...] = Field(
        default=(), description="Extended-profile values (outside the canonical model)."
    )


# --------------------------------------------------------------------------- #
# Merge + conflicts
# --------------------------------------------------------------------------- #


class MergedField(BaseModel):
    """One canonical field of the unified profile after merging."""

    model_config = ConfigDict(frozen=True)

    canonical_id: str = Field(..., description="Canonical profile field id.")
    value: str = Field(..., description="The winning merged value.")
    source_document_id: str = Field(..., description="Document the value came from.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Winning value's confidence.")
    validated: bool = Field(..., description="True if the value passed validation.")
    resolved: bool = Field(
        default=False, description="True if the user chose this value in a conflict."
    )


class ConflictOption(BaseModel):
    """One candidate value the user can pick during conflict resolution."""

    model_config = ConfigDict(frozen=True)

    document_id: str = Field(..., description="Document offering this value.")
    value: str = Field(..., description="The candidate value.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence.")
    valid: bool = Field(..., description="Validation Engine verdict.")


class FieldConflict(BaseModel):
    """Two or more documents disagree about one canonical field."""

    model_config = ConfigDict(frozen=True)

    canonical_id: str = Field(..., description="The disputed canonical field.")
    options: tuple[ConflictOption, ...] = Field(
        ..., description="Distinct candidate values, best-evidence first."
    )
    resolved: bool = Field(default=False, description="True once the user chose.")
    resolved_value: str | None = Field(
        default=None, description="The value the user picked (if resolved)."
    )


# --------------------------------------------------------------------------- #
# Per-session pipeline state
# --------------------------------------------------------------------------- #


class AppliedAnswer(BaseModel):
    """One session answer the intelligence pipeline wrote (so it may retract it)."""

    model_config = ConfigDict(frozen=True)

    field_id: str = Field(..., description="Interview-session field id written.")
    value: str = Field(..., description="Exactly the value stored in the session.")


class ProfileState(BaseModel):
    """
    The mutable per-session accumulator (mirrors the Session pattern):
    which documents were processed, which conflicts the user resolved, and
    which session answers this pipeline owns (and may therefore update or
    retract). Merge output is always recomputed from this state — it is never
    cached, so deleting a document can never leave stale merged values.
    """

    session_id: str = Field(..., description="The interview session this profile belongs to.")
    primary_form_id: str | None = Field(
        default=None,
        description="Schema id of the user-selected PRIMARY form (the final output).",
    )
    primary_form_label: str | None = Field(
        default=None, description="Display label of the selected primary form."
    )
    primary_document_id: str | None = Field(
        default=None,
        description=(
            "The uploaded document that IS the primary form (Phase 13). When "
            "set, the completed PDF is produced by filling THIS file, so the "
            "user gets their own SBI/HDFC/ICICI/Axis form back rather than a "
            "recreated CVL page. None = fall back to the bundled template."
        ),
    )
    documents: dict[str, DocumentProfile] = Field(
        default_factory=dict, description="Processed documents keyed by document_id."
    )
    resolutions: dict[str, str] = Field(
        default_factory=dict, description="canonical_id -> value the user chose."
    )
    applied: dict[str, AppliedAnswer] = Field(
        default_factory=dict,
        description="canonical_id -> session answer this pipeline wrote.",
    )
    asset_requirements: "FormAssetRequirements | None" = Field(
        default=None,
        description=(
            "Whether the ACTIVE primary form needs a photograph/signature, and "
            "where each belongs on the page. Recomputed whenever the primary "
            "form changes and cleared when it is deleted, so a form without a "
            "photo box never leaves a stale 'photo pending' behind. None = no "
            "primary form active, therefore no asset is ever asked for."
        ),
    )
    updated_at: datetime = Field(default_factory=utc_now, description="Last mutation (UTC).")


class ProfileRepository(ABC):
    """Persistence contract for per-session intelligence profiles."""

    @abstractmethod
    def get(self, session_id: str) -> ProfileState | None:
        """Return the state for a session, or None if none exists yet."""

    @abstractmethod
    def save(self, state: ProfileState) -> None:
        """Store (or replace) a session's profile state."""

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """Drop a session's profile state; return True if one existed."""
