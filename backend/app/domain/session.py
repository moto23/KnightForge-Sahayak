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


class Session(BaseModel):
    """
    The complete runtime state of one interview session.

    `answers` holds only values that passed the Validation Engine;
    `validation_errors` holds the latest rejected attempt per field. The four
    derived fields (current_field, completed_fields, progress_percentage,
    interview_status) are recomputed by SessionService after every mutation.
    """

    session_id: str = Field(..., description="Unique identifier of this session.")
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
    progress_percentage: float = Field(
        default=0.0,
        description="Percentage of REQUIRED fields validly answered (0–100).",
    )

    def touch(self) -> None:
        """Bump updated_at after a mutation."""
        self.updated_at = utc_now()
