"""
Chat-memory prompt (Phase 12) — rewrite a follow-up into a standalone question.

Multi-turn memory without touching the Knowledge RAG module: the RAG engine is
single-turn by design, so before retrieval the ChatService asks the LLM to
resolve pronouns/references from the recent transcript ("is it mandatory?" ->
"Is PAN mandatory for KYC?"). If the AI is unavailable, the raw question is
used as-is — memory degrades gracefully, it never blocks an answer.
"""

from app.domain.conversation import ConversationTurn  # noqa: F401 (doc reference)
from app.services.prompts.builder import PromptBundle

_SYSTEM = (
    "You rewrite follow-up questions from a KYC help chat into standalone "
    "questions. Use the conversation history ONLY to resolve references "
    "(pronouns like it/that/this, or elliptical questions). If the question "
    "is already self-contained, return it unchanged. Never answer the "
    "question, never add information the user didn't ask about, and keep the "
    "rewrite short. Reply with JSON exactly in this shape: "
    '{"question": "<standalone question>"}'
)


def build_standalone_question_prompt(
    history: list[tuple[str, str]], question: str
) -> PromptBundle:
    """
    `history` is the recent transcript as (role, content) pairs, oldest first.
    """
    lines = [f"{role}: {content}" for role, content in history]
    user = (
        "Conversation so far:\n"
        + ("\n".join(lines) if lines else "(empty)")
        + f"\n\nFollow-up question: {question}\n\nRewrite it as a standalone question."
    )
    return PromptBundle(system=_SYSTEM, user=user)
