"""
Pydantic request/response DTOs for the /intelligence endpoints (Phase 11).

Everything the frontend needs to render the Universal Document Intelligence
workspace: detected document types (badges), per-document canonical values,
the merged unified profile, open conflict cards, and exactly which interview
answers the pipeline applied (so the existing prefill-provenance/rollback
machinery keeps working unchanged).
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

import re

from app.domain.canonical_schema import canonical_registry
from app.domain.intelligence import (
    CanonicalValue,
    DocumentProfile,
    ExtraValue,
    FieldConflict,
    MergedField,
    ProfileState,
)
from app.services.document_intelligence_service import IntelligenceReport

# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class IntelligenceProcessRequest(BaseModel):
    """Body of POST /intelligence/process."""

    document_id: str = Field(..., description="Id of a previously uploaded document.")
    session_id: str = Field(..., description="Interview session receiving the profile.")


class PrimaryFormRequest(BaseModel):
    """Body of POST /intelligence/primary-form — the ONE final-output form."""

    session_id: str = Field(..., description="The interview session.")
    form_id: str = Field(..., description="Schema id of a KYC form (e.g. 'cvl_kyc').")


class ConflictResolveRequest(BaseModel):
    """Body of POST /intelligence/resolve — pick a candidate by document OR value."""

    session_id: str = Field(..., description="The session whose conflict is resolved.")
    canonical_id: str = Field(..., description="The disputed canonical field id.")
    document_id: str | None = Field(
        default=None, description="Choose the value contributed by this document."
    )
    value: str | None = Field(
        default=None, description="Choose this exact candidate value."
    )

    @model_validator(mode="after")
    def _one_choice_required(self) -> "ConflictResolveRequest":
        if self.document_id is None and self.value is None:
            raise ValueError("Provide either 'document_id' or 'value'.")
        return self


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #


def _canonical_label(canonical_id: str) -> str:
    field = canonical_registry.get(canonical_id)
    return field.label if field else canonical_id


class DocumentTypeResponse(BaseModel):
    """The classifier's verdict — powers the document-type badge."""

    schema_id: str = Field(..., description="Matched schema id, or 'unknown'.")
    label: str = Field(..., description="Human-readable document type.")
    kind: str = Field(..., description="kyc_form | identity_document | unknown.")
    confidence: float = Field(..., description="Classification confidence (0-1).")
    matched_markers: list[str] = Field(
        default_factory=list, description="Marker phrases actually found."
    )


class CanonicalValueResponse(BaseModel):
    """One canonical field's value extracted from one document."""

    canonical_id: str = Field(..., description="Canonical profile field id.")
    label: str = Field(..., description="Human-readable canonical field name.")
    value: str = Field(..., description="The normalized extracted value.")
    confidence: float = Field(..., description="Extraction confidence (0-1).")
    valid: bool = Field(..., description="Validation Engine verdict.")
    page_number: int = Field(..., description="Page the value was found on.")

    @classmethod
    def from_domain(cls, value: CanonicalValue) -> "CanonicalValueResponse":
        return cls(
            canonical_id=value.canonical_id,
            label=_canonical_label(value.canonical_id),
            value=value.value,
            confidence=value.confidence,
            valid=value.valid,
            page_number=value.page_number,
        )


class DocumentSummaryResponse(BaseModel):
    """Everything one document contributed to the unified profile."""

    document_id: str = Field(..., description="Uploaded document id.")
    filename: str = Field(..., description="Original filename.")
    sequence: int = Field(..., description="Upload order (earlier wins merge ties).")
    document_type: DocumentTypeResponse = Field(..., description="Detected type.")
    values: list[CanonicalValueResponse] = Field(
        default_factory=list, description="Canonical values from this document."
    )

    @classmethod
    def from_domain(cls, profile: DocumentProfile) -> "DocumentSummaryResponse":
        return cls(
            document_id=profile.document_id,
            filename=profile.filename,
            sequence=profile.sequence,
            document_type=DocumentTypeResponse(
                schema_id=profile.classification.schema_id,
                label=profile.classification.label,
                kind=profile.classification.kind,
                confidence=profile.classification.confidence,
                matched_markers=list(profile.classification.matched_markers),
            ),
            values=[CanonicalValueResponse.from_domain(v) for v in profile.values],
        )


class ExtraFieldResponse(BaseModel):
    """One EXTENDED-profile value — evidence with no canonical KYC home."""

    key: str = Field(..., description="Stable extended-profile key.")
    label: str = Field(..., description="Human-readable field name.")
    value: str = Field(..., description="The extracted value.")
    source_document_id: str = Field(..., description="Document the value came from.")
    source_document_name: str = Field(..., description="That document's filename.")
    source_type_label: str = Field(..., description="That document's detected type.")
    confidence: float = Field(..., description="Extraction confidence (0-1).")
    page_number: int = Field(..., description="Page the value was found on.")


class MissingFieldResponse(BaseModel):
    """A canonical KYC field the profile does NOT cover yet — the interview asks it."""

    canonical_id: str = Field(..., description="Canonical profile field id.")
    label: str = Field(..., description="Human-readable canonical field name.")
    session_field_id: str = Field(..., description="Interview field that will collect it.")
    required: bool = Field(..., description="Whether the interview requires it.")


class PrimaryFormResponse(BaseModel):
    """The user-selected primary form — the session's final output."""

    schema_id: str = Field(..., description="Selected KYC form schema id.")
    label: str = Field(..., description="Display label of the form.")


class MergedFieldResponse(BaseModel):
    """One canonical field of the unified profile after merging."""

    canonical_id: str = Field(..., description="Canonical profile field id.")
    label: str = Field(..., description="Human-readable canonical field name.")
    value: str = Field(..., description="The winning merged value.")
    source_document_id: str = Field(..., description="Document the value came from.")
    source_document_name: str = Field(..., description="That document's filename.")
    source_type_label: str = Field(..., description="That document's detected type.")
    confidence: float = Field(..., description="Winning value's confidence (0-1).")
    validated: bool = Field(..., description="Passed the deterministic validators.")
    resolved: bool = Field(..., description="True if chosen by the user in a conflict.")
    applied: bool = Field(..., description="True if written into the interview session.")
    session_field_id: str | None = Field(
        default=None, description="Interview field this canonical field feeds."
    )


class ConflictOptionResponse(BaseModel):
    """One candidate value inside a conflict card."""

    document_id: str = Field(..., description="Document offering this value.")
    document_name: str = Field(..., description="That document's filename.")
    document_type_label: str = Field(..., description="That document's detected type.")
    value: str = Field(..., description="The candidate value.")
    confidence: float = Field(..., description="Extraction confidence (0-1).")
    valid: bool = Field(..., description="Validation Engine verdict.")


class ConflictResponse(BaseModel):
    """Two or more documents disagree — the user must choose."""

    canonical_id: str = Field(..., description="The disputed canonical field.")
    label: str = Field(..., description="Human-readable canonical field name.")
    options: list[ConflictOptionResponse] = Field(
        ..., description="Distinct candidate values, best evidence first."
    )
    resolved: bool = Field(..., description="True once the user chose.")
    resolved_value: str | None = Field(default=None, description="The chosen value.")


# --------------------------------------------------------------------------- #
# Endpoint responses
# --------------------------------------------------------------------------- #


class UnifiedProfileResponse(BaseModel):
    """The session's unified canonical KYC profile — the merge engine's output."""

    session_id: str = Field(..., description="The interview session.")
    merge_status: str = Field(
        ..., description="empty | merged | conflicts (open conflicts pending)."
    )
    primary_form: PrimaryFormResponse | None = Field(
        default=None, description="The user-selected final-output form (if chosen)."
    )
    documents: list[DocumentSummaryResponse] = Field(
        default_factory=list, description="Processed documents, upload order."
    )
    fields: list[MergedFieldResponse] = Field(
        default_factory=list, description="Merged canonical fields."
    )
    missing_fields: list[MissingFieldResponse] = Field(
        default_factory=list,
        description="Canonical fields still unanswered — the interview asks only these.",
    )
    extra_fields: list[ExtraFieldResponse] = Field(
        default_factory=list,
        description="Extended-profile values (evidence outside the canonical model).",
    )
    conflicts: list[ConflictResponse] = Field(
        default_factory=list, description="Conflict cards (open and resolved)."
    )
    applied_field_ids: list[str] = Field(
        default_factory=list,
        description="Interview-session field ids this pipeline currently owns.",
    )
    progress_percentage: float = Field(..., description="Session progress now (0-100).")
    updated_at: datetime = Field(..., description="Last profile mutation (UTC).")

    @classmethod
    def from_report(cls, report: IntelligenceReport) -> "UnifiedProfileResponse":
        state: ProfileState = report.state
        documents = sorted(state.documents.values(), key=lambda d: d.sequence)
        open_conflicts = any(not c.resolved for c in report.conflicts)
        return cls(
            session_id=state.session_id,
            merge_status=(
                "empty"
                if not documents
                else "conflicts" if open_conflicts else "merged"
            ),
            primary_form=(
                PrimaryFormResponse(
                    schema_id=state.primary_form_id,
                    label=state.primary_form_label or state.primary_form_id,
                )
                if state.primary_form_id
                else None
            ),
            documents=[DocumentSummaryResponse.from_domain(d) for d in documents],
            fields=[_merged_field(m, state) for m in report.merged],
            missing_fields=_missing_fields(report),
            extra_fields=_extra_fields(documents, state),
            conflicts=[_conflict(c, state) for c in report.conflicts],
            applied_field_ids=[a.field_id for a in state.applied.values()],
            progress_percentage=report.session.progress_percentage,
            updated_at=state.updated_at,
        )


class IntelligenceProcessResponse(BaseModel):
    """Returned by POST /intelligence/process."""

    document: DocumentSummaryResponse = Field(
        ..., description="The document that was just classified and extracted."
    )
    applied_from_document: list[str] = Field(
        default_factory=list,
        description=(
            "Interview-session field ids applied whose merged value came from "
            "THIS document (for prefill-provenance tracking on the client)."
        ),
    )
    profile: UnifiedProfileResponse = Field(..., description="The re-merged profile.")

    @classmethod
    def from_report(cls, report: IntelligenceReport) -> "IntelligenceProcessResponse":
        state = report.state
        focus = report.document_id or ""
        document = state.documents.get(focus)
        if document is None:  # defensive: process always stores the document
            raise ValueError(f"Processed document '{focus}' missing from profile state.")
        applied_from_document = [
            state.applied[m.canonical_id].field_id
            for m in report.merged
            if m.source_document_id == focus and m.canonical_id in state.applied
        ]
        return cls(
            document=DocumentSummaryResponse.from_domain(document),
            applied_from_document=applied_from_document,
            profile=UnifiedProfileResponse.from_report(report),
        )


# --------------------------------------------------------------------------- #
# Internal mapping helpers
# --------------------------------------------------------------------------- #


def _missing_fields(report: IntelligenceReport) -> list[MissingFieldResponse]:
    """Canonical fields whose interview field is still unanswered — the gap list."""
    missing: list[MissingFieldResponse] = []
    for canonical in canonical_registry.all_fields():
        session_field = canonical_registry.session_field(canonical.id)
        if session_field is None:
            continue  # profile-only, never asked
        if session_field.id in report.session.answers:
            continue
        missing.append(
            MissingFieldResponse(
                canonical_id=canonical.id,
                label=canonical.label,
                session_field_id=session_field.id,
                required=session_field.required,
            )
        )
    return missing


def _extra_key(value: str) -> str:
    """Comparison key for extended values: casefolded, punctuation/space-blind."""
    return re.sub(r"[\W_]+", "", value).casefold()


def _extra_fields(
    documents: list[DocumentProfile], state: ProfileState
) -> list[ExtraFieldResponse]:
    """
    Aggregate every document's extended values, deduplicating identical
    (key, value) pairs across documents — best evidence (confidence) wins,
    provenance always preserved. Differing values for the same key are both
    kept: they are evidence, not merged answers.
    """
    best: dict[tuple[str, str], ExtraValue] = {}
    for document in documents:
        for extra in document.extras:
            dedupe = (extra.key, _extra_key(extra.value))
            current = best.get(dedupe)
            if current is None or extra.confidence > current.confidence:
                best[dedupe] = extra
    result = []
    for extra in sorted(best.values(), key=lambda e: (e.key, -e.confidence)):
        name, type_label = _source_meta(extra.document_id, state)
        result.append(
            ExtraFieldResponse(
                key=extra.key,
                label=extra.label,
                value=extra.value,
                source_document_id=extra.document_id,
                source_document_name=name,
                source_type_label=type_label,
                confidence=extra.confidence,
                page_number=extra.page_number,
            )
        )
    return result


def _source_meta(document_id: str, state: ProfileState) -> tuple[str, str]:
    document = state.documents.get(document_id)
    if document is None:
        return ("(deleted document)", "Unknown")
    return (document.filename, document.classification.label)


def _merged_field(item: MergedField, state: ProfileState) -> MergedFieldResponse:
    name, type_label = _source_meta(item.source_document_id, state)
    canonical = canonical_registry.get(item.canonical_id)
    applied = state.applied.get(item.canonical_id)
    return MergedFieldResponse(
        canonical_id=item.canonical_id,
        label=_canonical_label(item.canonical_id),
        value=item.value,
        source_document_id=item.source_document_id,
        source_document_name=name,
        source_type_label=type_label,
        confidence=item.confidence,
        validated=item.validated,
        resolved=item.resolved,
        applied=applied is not None,
        session_field_id=canonical.session_field_id if canonical else None,
    )


def _conflict(item: FieldConflict, state: ProfileState) -> ConflictResponse:
    options = []
    for option in item.options:
        name, type_label = _source_meta(option.document_id, state)
        options.append(
            ConflictOptionResponse(
                document_id=option.document_id,
                document_name=name,
                document_type_label=type_label,
                value=option.value,
                confidence=option.confidence,
                valid=option.valid,
            )
        )
    return ConflictResponse(
        canonical_id=item.canonical_id,
        label=_canonical_label(item.canonical_id),
        options=options,
        resolved=item.resolved,
        resolved_value=item.resolved_value,
    )
