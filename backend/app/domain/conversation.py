"""
Conversation domain models (Phase 5).

A conversation is the *transcript* of an interview session: alternating user
and assistant turns. It is pure memory for the AI's prompts — it holds no
answers, no validation results, and no flow state. The Session (Phase 4)
remains the single source of truth for all of those; deleting a session also
deletes its transcript.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.session import utc_now


class TurnRole(str, Enum):
    """Who produced a conversation turn."""

    USER = "user"
    ASSISTANT = "assistant"


class ConversationTurn(BaseModel):
    """One utterance in the interview transcript."""

    model_config = ConfigDict(frozen=True)

    role: TurnRole = Field(..., description="Who spoke: user or assistant.")
    content: str = Field(..., description="What was said, verbatim.")
    created_at: datetime = Field(
        default_factory=utc_now, description="When the turn happened (UTC)."
    )
