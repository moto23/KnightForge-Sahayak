"""
In-memory adapter for the ConversationRepository port (Phase 5).

Transcripts live in a plain dict of lists keyed by session id — same
rationale as the session store: zero infrastructure for the hackathon MVP,
PII vanishes on restart, and a database adapter later only touches
core/dependencies.py.
"""

from app.domain.conversation import ConversationTurn
from app.domain.repositories import ConversationRepository


class InMemoryConversationRepository(ConversationRepository):
    """Dict-backed transcript store; one list of turns per session."""

    def __init__(self) -> None:
        self._transcripts: dict[str, list[ConversationTurn]] = {}

    def append(self, session_id: str, turn: ConversationTurn) -> None:
        self._transcripts.setdefault(session_id, []).append(turn)

    def history(self, session_id: str) -> tuple[ConversationTurn, ...]:
        return tuple(self._transcripts.get(session_id, ()))

    def delete(self, session_id: str) -> bool:
        return self._transcripts.pop(session_id, None) is not None
