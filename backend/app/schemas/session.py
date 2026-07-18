"""
API request/response schemas for the session & interview endpoints.

Typed DTOs only — no logic. SessionResponse mirrors the domain Session
one-to-one (same field names) so `from_session()` is a mechanical mapping, but
keeping a separate DTO means the wire contract can evolve independently of the
domain model. Question metadata is the domain KYCField itself: it is already
the strongly-typed public contract for "a field", exposed unchanged since /schema.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import InterviewStatus
from app.domain.models import KYCField
from app.domain.session import InvalidAttempt, Session
from app.domain.validators.result import ValidationResult


class SessionResponse(BaseModel):
    """Complete public view of one interview session."""

    session_id: str = Field(..., description="Unique session identifier.")
    form_id: str = Field(..., description="Form being filled in this session.")
    created_at: datetime = Field(..., description="Creation time (UTC).")
    updated_at: datetime = Field(..., description="Last update time (UTC).")
    interview_status: InterviewStatus = Field(..., description="Lifecycle status.")
    current_field: str | None = Field(
        ..., description="Next required field to ask; null when complete."
    )
    completed_fields: list[str] = Field(
        ..., description="Fields with a stored valid answer, in answer order."
    )
    answers: dict[str, str] = Field(..., description="Valid answers only.")
    validation_errors: dict[str, InvalidAttempt] = Field(
        ..., description="Latest rejected attempt per field, kept separately."
    )
    progress_percentage: float = Field(
        ..., description="Percent of required fields validly answered (0–100)."
    )

    @classmethod
    def from_session(cls, session: Session) -> "SessionResponse":
        """Map the domain Session onto the wire DTO (field names match 1:1)."""
        return cls(**session.model_dump())


class CreateSessionResponse(BaseModel):
    """Response for POST /session — the new session plus the first question."""

    session: SessionResponse = Field(..., description="The newly created session.")
    next_question: KYCField | None = Field(
        ..., description="Full metadata of the first question to ask."
    )


class SubmitAnswerRequest(BaseModel):
    """Request body for POST /session/{id}/answer."""

    field_id: str = Field(
        ..., description="Id of the field being answered.", examples=["pan"]
    )
    value: str | None = Field(
        default=None, description="The user's raw answer.", examples=["ABCDE1234F"]
    )


class SubmitAnswerResponse(BaseModel):
    """Outcome of one answer: validation verdict, updated session, next question."""

    field_id: str = Field(..., description="The field that was answered.")
    accepted: bool = Field(..., description="True if the answer was stored.")
    result: ValidationResult = Field(..., description="Validation Engine verdict.")
    session: SessionResponse = Field(..., description="Refreshed session state.")
    next_question: KYCField | None = Field(
        ..., description="Next question to ask; null when the interview is complete."
    )


class NextQuestionResponse(BaseModel):
    """Response for GET /session/{id}/next."""

    session_id: str = Field(..., description="The session asked about.")
    completed: bool = Field(
        ..., description="True when no required questions remain."
    )
    question: KYCField | None = Field(
        ..., description="Full metadata of the next field; null when completed."
    )
    remaining_required: int = Field(
        ..., description="How many required fields are still unanswered."
    )


class ProgressResponse(BaseModel):
    """Response for GET /session/{id}/progress — drives a progress bar."""

    session_id: str = Field(..., description="The session measured.")
    interview_status: InterviewStatus = Field(..., description="Lifecycle status.")
    progress_percentage: float = Field(..., description="0–100, required fields only.")
    total_fields: int = Field(..., description="Every field on the form.")
    required_fields: int = Field(..., description="How many fields are mandatory.")
    answered_fields: int = Field(..., description="Valid answers stored (any field).")
    completed_required_fields: int = Field(
        ..., description="Required fields validly answered."
    )
    pending_required_fields: list[str] = Field(
        ..., description="Required field ids still missing, in form order."
    )
    invalid_fields: list[str] = Field(
        ..., description="Field ids whose latest attempt failed validation."
    )


class DeleteSessionResponse(BaseModel):
    """Response for DELETE /session/{id}."""

    session_id: str = Field(..., description="The session that was deleted.")
    deleted: bool = Field(..., description="Always true on success (404 otherwise).")


class ClearAnswerResponse(BaseModel):
    """Response for DELETE /session/{id}/answer/{field_id} — prefill rollback."""

    field_id: str = Field(..., description="The field whose answer was cleared.")
    cleared: bool = Field(..., description="Always true on success (404 otherwise).")
    session: SessionResponse = Field(
        ..., description="Refreshed session state (progress/next recomputed)."
    )
