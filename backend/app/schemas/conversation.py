"""
API request/response schemas for the AI conversation endpoints (Phase 5).

Typed DTOs only. Every response carries `ai_generated`: true means OpenAI
phrased the message, false means the deterministic fallback did (requirement:
the API must keep answering gracefully when OpenAI is unavailable). Question
metadata remains the domain KYCField, unchanged since /schema — the AI layer
adds phrasing, never new structure.
"""

from pydantic import BaseModel, Field

from app.domain.enums import InterviewStatus, Language
from app.domain.models import KYCField
from app.domain.validators.result import ValidationResult
from app.schemas.session import SessionResponse


class ExtractedAnswerModel(BaseModel):
    """A machine value pulled from natural language (not yet validated)."""

    field_id: str = Field(..., description="Field the value belongs to.")
    value: str | None = Field(..., description="Normalized value; null if none found.")
    confidence: str = Field(..., description="Extraction confidence: high/medium/low.")
    intent: str = Field(..., description="What the user meant: answer or question.")
    ai_generated: bool = Field(
        ..., description="True = OpenAI extracted it; false = deterministic fallback."
    )


class StartConversationRequest(BaseModel):
    """Request body for POST /conversation/start."""

    language: Language = Field(
        default=Language.ENGLISH,
        description="Language the assistant should speak: english/hinglish/hindi.",
    )


class StartConversationResponse(BaseModel):
    """A new session plus the conversationally phrased first question."""

    session_id: str = Field(..., description="The new session's id.")
    language: Language = Field(..., description="Language of this conversation.")
    message: str = Field(..., description="Assistant's greeting + first question.")
    ai_generated: bool = Field(..., description="True if OpenAI phrased the message.")
    question: KYCField | None = Field(
        ..., description="Machine metadata of the field being asked."
    )
    session: SessionResponse = Field(..., description="Full session state.")


class ReplyRequest(BaseModel):
    """Request body for POST /conversation/reply — one user message."""

    session_id: str = Field(..., description="Session this message belongs to.")
    message: str = Field(
        ..., min_length=1, description="What the user said, verbatim.",
        examples=["mera pan hai abcde1234f"],
    )
    language: Language = Field(default=Language.ENGLISH, description="Reply language.")


class ReplyResponse(BaseModel):
    """Everything that happened for one user message."""

    session_id: str = Field(..., description="The session replied to.")
    message: str = Field(..., description="Assistant's conversational reply.")
    ai_generated: bool = Field(..., description="True if OpenAI phrased the reply.")
    intent: str = Field(
        ..., description="How the message was understood: answer/question/none."
    )
    extraction: ExtractedAnswerModel | None = Field(
        ..., description="What was extracted from the message, if anything."
    )
    accepted: bool | None = Field(
        ..., description="Validator verdict for a submitted answer; null if none."
    )
    validation: ValidationResult | None = Field(
        ..., description="Full Validation Engine result; null if nothing submitted."
    )
    next_question: KYCField | None = Field(
        ..., description="Next field per the Session Engine; null when complete."
    )
    interview_status: InterviewStatus = Field(..., description="Session status.")
    progress_percentage: float = Field(..., description="Progress after this reply.")


class ExplainRequest(BaseModel):
    """Request body for POST /conversation/explain."""

    session_id: str = Field(..., description="Session asking for the explanation.")
    field_id: str | None = Field(
        default=None,
        description="Field to explain; omit for the field currently being asked.",
        examples=["pan"],
    )
    language: Language = Field(default=Language.ENGLISH, description="Reply language.")


class ExplainResponse(BaseModel):
    """A plain-language explanation of one field."""

    session_id: str = Field(..., description="The session explained to.")
    field_id: str | None = Field(
        ..., description="Field that was explained; null when interview is complete."
    )
    message: str = Field(..., description="The explanation itself.")
    ai_generated: bool = Field(..., description="True if OpenAI wrote it.")


class ExtractRequest(BaseModel):
    """Request body for POST /conversation/extract — extraction only, no storing."""

    session_id: str = Field(..., description="Session providing conversation context.")
    message: str = Field(
        ..., min_length=1, description="Natural-language text to extract from.",
        examples=["my email id is rahul.sharma@gmail.com"],
    )
    field_id: str | None = Field(
        default=None, description="Target field; omit for the current field."
    )
    language: Language = Field(default=Language.ENGLISH, description="Language hint.")


class ExtractResponse(BaseModel):
    """The structured extraction result — nothing validated, nothing stored."""

    session_id: str = Field(..., description="The session extracted for.")
    extraction: ExtractedAnswerModel = Field(..., description="What was extracted.")
