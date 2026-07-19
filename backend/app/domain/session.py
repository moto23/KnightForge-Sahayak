"""
Session domain model — the runtime state of one KYC interview.

Unlike the schema models (frozen reference data), a Session is MUTABLE runtime
state: it accumulates answers as the interview progresses. It is still a pure
domain object — no I/O, no HTTP, no persistence concerns. The repository stores
it; SessionService is the only code allowed to mutate it (and always refreshes
the derived fields — current_field, completed_fields, progress_percentage,
interview_status — after every change, so the stored object is never stale).

Storage rule for answers (single source of truth per field):
- a VALID submission puts the value in `answers` and clears any prior error;
- an INVALID submission records the attempt in `validation_errors` and removes
  any prior valid answer (the latest submission always wins).
So a field id can never appear in both maps at once.
"""

from collections.abc import Mapping
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import InterviewStatus


def utc_now() -> datetime:
    """Timezone-aware 'now' — the single timestamp source for sessions."""
    return datetime.now(timezone.utc)


class InvalidAttempt(BaseModel):
    """
    A rejected answer, kept separately from valid answers so the client can
    show the user exactly what they typed and why it was refused.
    """

    model_config = ConfigDict(frozen=True)

    value: str | None = Field(..., description="The raw value the user submitted.")
    code: str = Field(..., description="Machine-readable failure code (e.g. invalid_pan).")
    message: str = Field(..., description="Human-readable explanation of the failure.")


class ConditionalRequirement(BaseModel):
    """
    One "this field matters only when…" rule, evaluated against answers.

    Deliberately data-only and form-agnostic so an unseen form can declare its
    own conditions in JSON without a code change:

        equals        — required when `when_field` holds one of these values
                        (CVL: nationality_other when nationality == "other")
        unless_answered — required only while `when_field` has NO answer
                        (CVL: PAN-exempt Proof of Identity, needed only when
                        no PAN was given)
    """

    model_config = ConfigDict(frozen=True)

    field_id: str = Field(..., description="The field this rule can make required.")
    when_field: str = Field(..., description="The field whose state is inspected.")
    equals: tuple[str, ...] = Field(
        default=(), description="Values of when_field that trigger the requirement."
    )
    unless_answered: bool = Field(
        default=False,
        description="True = required only while when_field is unanswered.",
    )

    def applies(self, answers: Mapping[str, str]) -> bool:
        """Is `field_id` required given these answers?"""
        current = (answers.get(self.when_field) or "").strip()
        if self.unless_answered:
            return not current
        return current.lower() in {v.lower() for v in self.equals}


class Session(BaseModel):
    """
    The complete runtime state of one interview session.

    `answers` holds only values that passed the Validation Engine;
    `validation_errors` holds the latest rejected attempt per field. The four
    derived fields (current_field, completed_fields, progress_percentage,
    interview_status) are recomputed by SessionService after every mutation.
    """

    session_id: str = Field(..., description="Unique identifier of this session.")
    owner_id: str | None = Field(
        default=None,
        description=(
            "Id of the signed-in user this session belongs to, or None for a "
            "guest session.\n\n"
            "A session holds the applicant's PAN, Aadhaar, date of birth, "
            "address, photograph and signature, and every asset and generated "
            "PDF hangs off it. Before this field the only thing standing "
            "between one applicant's KYC data and another's was the secrecy of "
            "a UUID in a URL: any signed-in user who presented someone else's "
            "session id could read, re-fill, download or delete it. Ownership "
            "is recorded here so the API can refuse that server-side.\n\n"
            "None means a guest created it, which the product deliberately "
            "supports. Such a session is CLAIMED by the first signed-in user "
            "to touch it, so signing in part-way through does not lose the "
            "work and the session becomes protected from that point on."
        ),
    )
    form_id: str = Field(..., description="Id of the form being filled.")
    created_at: datetime = Field(..., description="When the session was created (UTC).")
    updated_at: datetime = Field(..., description="Last mutation time (UTC).")
    interview_status: InterviewStatus = Field(
        default=InterviewStatus.IN_PROGRESS,
        description="Lifecycle status; COMPLETED once every required field is valid.",
    )
    current_field: str | None = Field(
        default=None,
        description="Id of the next required field to ask; None when complete.",
    )
    completed_fields: list[str] = Field(
        default_factory=list,
        description="Ids of fields with a stored valid answer, in answer order.",
    )
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="field id -> validated value. Only VALID answers live here.",
    )
    validation_errors: dict[str, InvalidAttempt] = Field(
        default_factory=dict,
        description="field id -> latest rejected attempt. Kept apart from answers.",
    )
    skipped_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Fields the user explicitly declined to answer.\n\n"
            "A real state, deliberately NOT a value. Saying 'skip' or "
            "\"don't know\" used to leave the field simply unanswered, and the "
            "next question is 'the first required field without an answer' - so "
            "the same question came straight back, forever. Writing the word "
            "'skip' into the field instead would have been worse: 'skip' is not "
            "a CKYC number.\n\n"
            "A skipped field is passed over when choosing the next question and "
            "counts as settled for completion, but stores NO value, so nothing "
            "false reaches the profile or the printed form. It stays editable: "
            "answering it later clears the skip."
        ),
    )
    progress_percentage: float = Field(
        default=0.0,
        description="Percentage of REQUIRED fields validly answered (0–100).",
    )
    conditional_required: list["ConditionalRequirement"] = Field(
        default_factory=list,
        description=(
            "Rules that make a field required only in certain states (Phase "
            "14): CVL's PAN-exempt Proof of Identity, 'other' free-text "
            "companions, net-worth as an alternative to income. Re-evaluated "
            "on every refresh, so the interview asks a conditional field the "
            "moment it becomes relevant and drops it when it stops being."
        ),
    )
    required_field_ids: list[str] | None = Field(
        default=None,
        description=(
            "Field ids the ACTIVE primary form requires (Phase 13). Set when a "
            "primary form is chosen, so an SBI/HDFC/ICICI/Axis session is "
            "measured and interviewed against ITS requirements, not a fixed "
            "CVL list.\n\n"
            "THREE distinct states — the empty list is NOT the same as None:\n"
            "  None  = no form scope; use the registry's own required set\n"
            "          (a plain guest interview with no primary form chosen).\n"
            "  []    = a form WAS active and has been retired (its document was "
            "          deleted). There is no questionnaire at all: nothing is "
            "          required, progress is not measured, and the interview "
            "          has no questions until a new primary form is uploaded.\n"
            "  [...] = the active form's own required fields.\n\n"
            "Collapsing [] into None was the Phase 15 regression: deleting the "
            "primary form fell back to the registry default, so Progress and "
            "the interview kept demanding ~21 CVL fields for a form that no "
            "longer existed."
        ),
    )

    def touch(self) -> None:
        """Bump updated_at after a mutation."""
        self.updated_at = utc_now()
