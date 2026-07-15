"""
In-memory SessionRepository adapter.

A plain dict keyed by session_id. Fits the hackathon MVP perfectly: zero setup,
instant reads/writes, sessions are naturally ephemeral (PII vanishes on
restart — a feature, not a bug, for KYC data). Implements the domain's
SessionRepository port, so swapping in PostgreSQL later means writing one new
adapter — services never change.

Note on concurrency: FastAPI runs our (async) routes on a single event loop,
so plain dict operations are safe here. A database adapter would handle its own
transactional guarantees.
"""

from app.domain.repositories import SessionRepository
from app.domain.session import Session


class InMemorySessionRepository(SessionRepository):
    """Dict-backed session store — the MVP persistence adapter."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def add(self, session: Session) -> None:
        """Store a brand-new session."""
        self._sessions[session.session_id] = session

    def get(self, session_id: str) -> Session | None:
        """Return the session with this id, or None if it doesn't exist."""
        return self._sessions.get(session_id)

    def save(self, session: Session) -> None:
        """
        Persist changes (upsert). With in-memory objects this is technically a
        no-op re-assignment, but services call it after every mutation so the
        code is already correct for a real database adapter.
        """
        self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> bool:
        """Remove a session; True if it existed."""
        return self._sessions.pop(session_id, None) is not None
