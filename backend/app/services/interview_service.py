"""
InterviewService — the conversational flow orchestrator (no AI involved).

Sits one level above SessionService and answers flow questions: "what do we ask
next?", "how far along are we?", "can this interview be completed?". It never
touches the repository directly and never validates anything itself — it
composes SessionService (state), FormService (schema), and NextQuestionEngine
(question selection).

In Phase 5, the OpenAI layer will WRAP this service: the LLM phrases the
question returned by `next_question()` conversationally, but flow control and
validation stay 100% deterministic right here.
"""

import logging
from dataclasses import dataclass

from app.core.exceptions import InterviewIncompleteError
from app.domain.enums import InterviewStatus
from app.domain.models import KYCField
from app.domain.next_question import NextQuestionEngine, next_question_engine
from app.domain.session import Session
from app.domain.validators.result import ValidationResult
from app.services.form_service import FormService, form_service
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgressReport:
    """Everything a client needs to render an interview progress bar."""

    session_id: str
    interview_status: InterviewStatus
    progress_percentage: float
    total_fields: int                      # every field on the form
    required_fields: int                   # how many are mandatory
    answered_fields: int                   # valid answers stored (any field)
    completed_required_fields: int         # required fields validly answered
    pending_required_fields: tuple[str, ...]   # required ids still missing
    invalid_fields: tuple[str, ...]        # ids whose latest attempt failed


@dataclass(frozen=True)
class AnswerOutcome:
    """Result of one answer submission: what happened + what to ask next."""

    session: Session
    result: ValidationResult
    next_question: KYCField | None


class InterviewService:
    """Deterministic interview flow over the KYC schema."""

    def __init__(
        self,
        sessions: SessionService,
        forms: FormService = form_service,
        next_engine: NextQuestionEngine = next_question_engine,
    ) -> None:
        self._sessions = sessions
        self._forms = forms
        self._next_engine = next_engine

    def start_interview(self) -> tuple[Session, KYCField | None]:
        """Create a session and return it with the first question's metadata."""
        session = self._sessions.create_session()
        return session, self._current_question(session)

    def submit_answer(
        self, session_id: str, field_id: str, value: str | None
    ) -> AnswerOutcome:
        """
        Submit one answer: it is validated by the Validation Engine, stored
        (valid) or recorded as an error (invalid), and the next question is
        recomputed — all in one call.
        """
        session, result = self._sessions.update_answer(session_id, field_id, value)
        return AnswerOutcome(
            session=session,
            result=result,
            next_question=self._current_question(session),
        )

    def next_question(self, session_id: str) -> tuple[Session, KYCField | None]:
        """Return the next field to ask (full metadata), or None when done."""
        session = self._sessions.get_session(session_id)
        return session, self._current_question(session)

    def current_progress(self, session_id: str) -> ProgressReport:
        """Compute the full progress report for a session, schema-driven."""
        session = self._sessions.get_session(session_id)
        all_fields = self._forms.get_all_fields()
        required = self._forms.get_required_fields()
        pending_required = self._next_engine.remaining_required_fields(session.answers)

        return ProgressReport(
            session_id=session.session_id,
            interview_status=session.interview_status,
            progress_percentage=session.progress_percentage,
            total_fields=len(all_fields),
            required_fields=len(required),
            answered_fields=len(session.answers),
            completed_required_fields=len(required) - len(pending_required),
            pending_required_fields=tuple(f.id for f in pending_required),
            invalid_fields=tuple(session.validation_errors),
        )

    def complete_interview(self, session_id: str) -> Session:
        """
        Explicitly assert an interview is complete (the gate later phases —
        e.g. PDF generation — will call before producing output).

        Completion also happens automatically as the last required answer is
        accepted; this method re-verifies and raises a typed 409 error listing
        the missing fields if anything required is still unanswered.
        """
        session = self._sessions.get_session(session_id)
        remaining = self._next_engine.remaining_required_fields(session.answers)
        if remaining:
            raise InterviewIncompleteError(tuple(f.id for f in remaining))
        logger.info("Interview complete for session %s", session.session_id)
        return session

    def _current_question(self, session: Session) -> KYCField | None:
        """Full metadata of the session's current field (None when complete)."""
        if session.current_field is None:
            return None
        return self._forms.get_field(session.current_field)
