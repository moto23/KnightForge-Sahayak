"""
In-memory ProfileRepository adapter (Phase 11).

Same MVP pattern as every other repository: a thread-safe dict keyed by
session id. A database adapter later implements the identical ProfileRepository
interface and nothing in the service layer changes.
"""

from threading import Lock

from app.domain.intelligence import ProfileRepository, ProfileState


class InMemoryProfileRepository(ProfileRepository):
    """Thread-safe in-memory store for per-session intelligence profiles."""

    def __init__(self) -> None:
        self._states: dict[str, ProfileState] = {}
        self._lock = Lock()

    def get(self, session_id: str) -> ProfileState | None:
        with self._lock:
            return self._states.get(session_id)

    def save(self, state: ProfileState) -> None:
        with self._lock:
            self._states[state.session_id] = state

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._states.pop(session_id, None) is not None
