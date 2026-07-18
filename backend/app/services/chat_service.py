"""
ChatService (Phase 12) — persistent Knowledge Assistant conversations.

Signed-in users get everything guests don't: saved conversations, history,
continue-where-you-left-off, rename/delete/search — and multi-turn memory.
The Knowledge RAG engine itself is UNTOUCHED: this service is a persistence
and memory layer AROUND KnowledgeService.query().

Multi-turn memory: RAG retrieval is single-turn, so before querying we ask
the LLM to rewrite a follow-up ("is it mandatory?") into a standalone
question using the recent transcript. If the AI is offline the raw question
is used — degraded memory, never a blocked answer.

Ownership is enforced in EVERY query: a conversation id belonging to another
user is indistinguishable from a missing one (404), so ids can't be probed.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ChatNotFoundError
from app.domain.knowledge import KnowledgeAnswer
from app.infrastructure.db.models import ChatConversation, ChatMessage
from app.services.ai_service import AIService, AIUnavailableError
from app.services.knowledge_service import KnowledgeService
from app.services.prompts import build_standalone_question_prompt

logger = logging.getLogger(__name__)

# How many recent turns feed the follow-up rewriter (memory window).
_MEMORY_TURNS = 6
_TITLE_MAX = 60


class ChatService:
    """CRUD + RAG-answering over a user's saved conversations."""

    def __init__(self, db: Session, knowledge: KnowledgeService, ai: AIService) -> None:
        self._db = db
        self._knowledge = knowledge
        self._ai = ai

    # ------------------------------------------------------------------ #
    # Conversations
    # ------------------------------------------------------------------ #

    def create(self, user_id: str, title: str | None = None) -> ChatConversation:
        conversation = ChatConversation(
            user_id=user_id, title=(title or "New conversation").strip()[:_TITLE_MAX]
        )
        self._db.add(conversation)
        self._db.commit()
        return conversation

    def list_conversations(self, user_id: str, query: str | None = None) -> list[ChatConversation]:
        """The user's conversations, newest activity first; optional search."""
        stmt = select(ChatConversation).where(ChatConversation.user_id == user_id)
        if query and query.strip():
            needle = f"%{query.strip()}%"
            # Search titles AND message bodies (subquery keeps results distinct).
            matching = (
                select(ChatMessage.conversation_id)
                .where(ChatMessage.content.ilike(needle))
                .scalar_subquery()
            )
            stmt = stmt.where(
                or_(
                    ChatConversation.title.ilike(needle),
                    ChatConversation.id.in_(matching),
                )
            )
        stmt = stmt.order_by(ChatConversation.updated_at.desc())
        return list(self._db.scalars(stmt))

    def get(self, user_id: str, chat_id: str) -> ChatConversation:
        """Fetch one conversation, enforcing ownership (foreign id -> 404)."""
        conversation = self._db.scalar(
            select(ChatConversation).where(
                ChatConversation.id == chat_id,
                ChatConversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise ChatNotFoundError(chat_id)
        return conversation

    def rename(self, user_id: str, chat_id: str, title: str) -> ChatConversation:
        conversation = self.get(user_id, chat_id)
        conversation.title = title.strip()[:_TITLE_MAX] or conversation.title
        self._db.commit()
        return conversation

    def delete(self, user_id: str, chat_id: str) -> None:
        conversation = self.get(user_id, chat_id)
        self._db.delete(conversation)  # messages cascade
        self._db.commit()

    # ------------------------------------------------------------------ #
    # Messages — the RAG round-trip with memory
    # ------------------------------------------------------------------ #

    def messages(self, user_id: str, chat_id: str) -> list[ChatMessage]:
        conversation = self.get(user_id, chat_id)
        return list(conversation.messages)

    def ask(
        self, user_id: str, chat_id: str, question: str
    ) -> tuple[ChatMessage, ChatMessage, KnowledgeAnswer]:
        """
        One full turn: persist the user's question, answer it through the
        (untouched) Knowledge RAG engine with follow-up rewriting, persist the
        assistant's answer with its citations, and return all three.
        """
        conversation = self.get(user_id, chat_id)
        history = [(m.role, m.content) for m in conversation.messages][-_MEMORY_TURNS:]

        user_message = ChatMessage(
            conversation_id=conversation.id, role="user", content=question.strip()
        )
        self._db.add(user_message)

        answer = self._knowledge.query(self._standalone(history, question))

        assistant_message = ChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=answer.answer,
            citations_json=json.dumps(
                [
                    {
                        "document_name": item.chunk.document_name,
                        "source": item.chunk.source,
                        "page_number": item.chunk.page_number,
                        "similarity": item.similarity,
                        "snippet": " ".join(item.chunk.text.split())[:280],
                    }
                    for item in answer.citations
                ]
            ),
            confident=answer.confident,
            generator=answer.generator,
        )
        self._db.add(assistant_message)

        # First real question becomes the conversation title.
        if conversation.title in ("", "New conversation"):
            conversation.title = question.strip()[:_TITLE_MAX]
        # NOTE: not user_message.created_at — Python-side column defaults are
        # only applied at flush, so that attribute is still None here.
        conversation.updated_at = datetime.now(timezone.utc)
        self._db.commit()
        return user_message, assistant_message, answer

    def _standalone(self, history: list[tuple[str, str]], question: str) -> str:
        """Resolve follow-up references via the LLM; fall back to the raw text."""
        if not history:
            return question
        try:
            data = self._ai.complete_json(
                build_standalone_question_prompt(history, question)
            )
            rewritten = str(data.get("question") or "").strip()
            if rewritten:
                if rewritten != question:
                    logger.info("Chat memory rewrite: %r -> %r", question, rewritten)
                return rewritten
        except AIUnavailableError:
            pass  # no AI -> no memory rewrite, but the question still answers
        return question
