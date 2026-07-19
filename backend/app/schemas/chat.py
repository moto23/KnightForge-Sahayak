"""Pydantic request/response DTOs for the /chats endpoints (Phase 12)."""

import json
from datetime import datetime

from pydantic import BaseModel, Field

from app.infrastructure.db.models import ChatConversation, ChatMessage


class CreateChatRequest(BaseModel):
    """Body of POST /chats."""

    title: str | None = Field(
        default=None, max_length=160, description="Optional title (defaults to first question)."
    )


class RenameChatRequest(BaseModel):
    """Body of PATCH /chats/{chat_id}."""

    title: str = Field(..., min_length=1, max_length=160, description="New title.")


class AskRequest(BaseModel):
    """Body of POST /chats/{chat_id}/messages."""

    # min_length 1, matching /knowledge/query: "Hi" is two characters and was
    # rejected with a 422 before routing could ever see it.
    question: str = Field(..., min_length=1, max_length=500, description="The user's question.")
    session_id: str | None = Field(
        None,
        description=(
            "The active KYC session, when there is one, so questions about the "
            "user's own progress are answered from that session's authoritative "
            "state instead of from the document corpus."
        ),
    )


class ChatCitation(BaseModel):
    """One source passage an assistant answer is grounded in (persisted)."""

    document_name: str = Field(..., description="Human-readable document title.")
    source: str = Field(..., description="Source file the passage came from.")
    page_number: int = Field(..., description="1-based page number.")
    similarity: float = Field(..., description="Retrieval similarity (0-1).")
    snippet: str = Field(..., description="Short excerpt of the passage.")


class ChatMessageResponse(BaseModel):
    """One persisted turn of a conversation."""

    message_id: str = Field(..., description="Message id.")
    role: str = Field(..., description="user | assistant.")
    content: str = Field(..., description="The message text.")
    citations: list[ChatCitation] = Field(
        default_factory=list, description="Assistant-only source citations."
    )
    confident: bool | None = Field(
        default=None, description="Assistant-only: false = honest 'I don't know'."
    )
    generator: str | None = Field(
        default=None, description="Assistant-only: model name / fallback / none."
    )
    created_at: datetime = Field(..., description="When the turn happened (UTC).")

    @classmethod
    def from_message(cls, message: ChatMessage) -> "ChatMessageResponse":
        citations: list[ChatCitation] = []
        if message.citations_json:
            try:
                citations = [ChatCitation(**c) for c in json.loads(message.citations_json)]
            except (ValueError, TypeError):
                citations = []  # a corrupt row must never break history loading
        return cls(
            message_id=message.id,
            role=message.role,
            content=message.content,
            citations=citations,
            confident=message.confident,
            generator=message.generator,
            created_at=message.created_at,
        )


class ChatSummaryResponse(BaseModel):
    """One conversation in the history list."""

    chat_id: str = Field(..., description="Conversation id.")
    title: str = Field(..., description="Conversation title.")
    created_at: datetime = Field(..., description="Created (UTC).")
    updated_at: datetime = Field(..., description="Last activity (UTC).")

    @classmethod
    def from_conversation(cls, conversation: ChatConversation) -> "ChatSummaryResponse":
        return cls(
            chat_id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class ChatDetailResponse(BaseModel):
    """A conversation with its full transcript — 'continue previous chat'."""

    chat: ChatSummaryResponse = Field(..., description="The conversation.")
    messages: list[ChatMessageResponse] = Field(..., description="All turns, oldest first.")

    @classmethod
    def from_conversation(cls, conversation: ChatConversation) -> "ChatDetailResponse":
        return cls(
            chat=ChatSummaryResponse.from_conversation(conversation),
            messages=[ChatMessageResponse.from_message(m) for m in conversation.messages],
        )


class ChatListResponse(BaseModel):
    """Returned by GET /chats."""

    total: int = Field(..., description="Number of conversations returned.")
    chats: list[ChatSummaryResponse] = Field(..., description="Newest activity first.")


class AskResponse(BaseModel):
    """Returned by POST /chats/{chat_id}/messages — the full turn."""

    chat_id: str = Field(..., description="The conversation answered in.")
    user_message: ChatMessageResponse = Field(..., description="The stored question.")
    assistant_message: ChatMessageResponse = Field(..., description="The stored answer.")


class DeleteChatResponse(BaseModel):
    """Returned by DELETE /chats/{chat_id}."""

    deleted: bool = Field(default=True, description="Always true on success.")
    chat_id: str = Field(..., description="The deleted conversation id.")
