"""
SessionService — lifecycle and state management for interview sessions.

Owns every mutation of a Session: create, read, answer updates, delete. Its one
invariant: after ANY mutation the session's derived fields (current_field,
completed_fields, progress_percentage, interview_status) are recomputed via
`_refresh()`, so a session read from the repository is never stale.

Answer rule (requirement: store valid and invalid separately):
- VALID submission  -> value stored in `answers`, any prior error cleared.
- INVALID submission -> attempt stored in `validation_errors`, any prior valid
  answer removed (the latest submission always wins; a field id never appears
  in both maps).
- Blank submission on an OPTIONAL field -> treated as a skip: passes
  validation, clears any stored value.

All collaborators are injected (defaulting to singletons), so the whole service
tests with a fresh InMemorySessionRepository and no HTTP.
"""

import logging
from uuid import uuid4

from app.core.exceptions import SessionNotFoundError
from app.domain.enums import InterviewStatus
from app.domain.next_question import NextQuestionEngine, next_question_engine
from app.domain.repositories import SessionRepository
from app.domain.session import InvalidAttempt, Session, utc_now
from app.domain.validators.result import ValidationResult
from app.services.form_service import FormService, form_service
from app.services.form_validation_service import (
    FormValidationService,
    form_validation_service,
)

logger = logging.getLogger(__name__)


class SessionService:
    """Create, read, mutate, and delete interview sessions."""

    def __init__(
        self,
        repository: SessionRepository,
        forms: FormService = form_service,
        validation: FormValidationService = form_validation_service,
        next_question: NextQuestionEngine = next_question_engine,
    ) -> None:
        self._repository = repository
        self._forms = forms
        self._validation = validation
        self._next_question = next_question

    # ------------------------------------------------------------------ CRUD

    def create_session(self) -> Session:
        """Create a fresh session pointing at the first required question."""
        now = utc_now()
        session = Session(
            session_id=uuid4().hex,
            form_id=self._forms.get_form().id,
            created_at=now,
            updated_at=now,
        )
        self._refresh(session)  # sets current_field / progress for an empty session
        self._repository.add(session)
        logger.info("Session created: %s", session.session_id)
        return session

    def get_session(self, session_id: str) -> Session:
        """Return the session or raise the typed 404 domain error."""
        session = self._repository.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    def delete_session(self, session_id: str) -> None:
        """Delete a session; raises SessionNotFoundError if it doesn't exist."""
        if not self._repository.delete(session_id):
            raise SessionNotFoundError(session_id)
        logger.info("Session deleted: %s", session_id)

    # --------------------------------------------------------------- answers

    def update_answer(
        self, session_id: str, field_id: str, value: str | None
    ) -> tuple[Session, ValidationResult]:
        """
        Validate one answer through the Validation Engine and store the outcome.

        Returns the refreshed session plus the ValidationResult so callers can
        report exactly why an answer was accepted or rejected. Raises
        KYCFieldNotFoundError (404) for unknown field ids and
        SessionNotFoundError (404) for unknown sessions.
        """
        session = self.get_session(session_id)

        # Delegates to the deterministic Validation Engine — this service never
        # implements validation rules itself.
        result = self._validation.validate_field(field_id, value)

        if result.valid:
            if value is None or not value.strip():
                # Valid + blank can only happen for optional fields — a skip.
                session.answers.pop(field_id, None)
            else:
                session.answers[field_id] = value.strip()
            session.validation_errors.pop(field_id, None)
        else:
            session.validation_errors[field_id] = InvalidAttempt(
                value=value, code=result.code, message=result.message
            )
            # Latest submission wins: an invalid retry invalidates the field.
            session.answers.pop(field_id, None)

        self._refresh(session)
        session.touch()
        self._repository.save(session)
        logger.info(
            "Answer for '%s' on session %s: %s",
            field_id,
            session.session_id,
            "accepted" if result.valid else f"rejected ({result.code})",
        )
        return session, result

    def clear_answer(self, session_id: str, field_id: str) -> Session:
        """
        Remove one field's stored answer (and/or invalid attempt) entirely,
        returning the field to PENDING — then recompute all derived state.

        This is NOT the same as submitting a blank value: for a required field
        a blank submission records an invalid attempt, whereas clearing erases
        the field from both maps. Used to roll back AI-prefilled values when
        their source document is deleted. Idempotent for already-empty fields;
        unknown ids raise the typed 404s (SessionNotFoundError /
        KYCFieldNotFoundError via FormService.get_field).
        """
        session = self.get_session(session_id)
        self._forms.get_field(field_id)  # typed 404 for unknown field ids

        session.answers.pop(field_id, None)
        session.validation_errors.pop(field_id, None)

        self._refresh(session)
        session.touch()
        self._repository.save(session)
        logger.info(
            "Answer for '%s' cleared on session %s", field_id, session.session_id
        )
        return session

    # ---------------------------------------------------------- derived state

    def _refresh(self, session: Session) -> None:
        """
        Recompute all derived fields from `answers` — the single place where
        progress %, completed fields, the current question, and interview
        status are calculated. Everything is driven by the schema; nothing is
        hardcoded.
        """
        next_field = self._next_question.next_required_field(session.answers)
        required = self._forms.get_required_fields()
        answered_required = sum(1 for f in required if f.id in session.answers)

        session.current_field = next_field.id if next_field else None
        session.completed_fields = list(session.answers)
        session.progress_percentage = round(
            (answered_required / len(required)) * 100, 1
        )
        # Completion is automatic (and reversible if a required answer is later
        # invalidated): COMPLETED exactly when no required field is missing.
        session.interview_status = (
            InterviewStatus.COMPLETED
            if next_field is None
            else InterviewStatus.IN_PROGRESS
        )
