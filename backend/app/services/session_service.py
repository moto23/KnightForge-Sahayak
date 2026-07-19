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

from app.core.exceptions import FieldNotSkippableError, SessionNotFoundError
from app.domain.enums import InterviewStatus
from app.domain.models import KYCField
from app.domain.next_question import NextQuestionEngine, next_question_engine
from app.domain.repositories import SessionRepository
from app.domain.session import (
    ConditionalRequirement,
    InvalidAttempt,
    Session,
    utc_now,
)
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

    def create_session(self, owner_id: str | None = None) -> Session:
        """
        Create a fresh session pointing at the first required question.

        `owner_id` is the signed-in user, or None for a guest — see
        Session.owner_id and `assert_owner`.
        """
        now = utc_now()
        session = Session(
            session_id=uuid4().hex,
            owner_id=owner_id,
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

    def may_access(self, session_id: str, user_id: str | None) -> bool:
        """
        True when `user_id` is entitled to this session — WITHOUT claiming it.

        The read-only companion to `assert_owner`, for filtering lists. Listing
        must never have the side effect of taking ownership of every unowned
        session it happens to look at.
        """
        session = self._repository.get(session_id)
        if session is None:
            return False
        return session.owner_id is None or session.owner_id == user_id

    def assert_owner(self, session_id: str, user_id: str | None) -> Session:
        """
        Return the session only if `user_id` is entitled to it.

        The rules, in order:

          * OWNED by this user            -> allowed.
          * OWNED by somebody else        -> refused, as NOT FOUND. A 403 would
                                             confirm the id belongs to a real
                                             session, which is itself a leak;
                                             an attacker probing ids learns
                                             nothing either way.
          * UNOWNED and the caller is
            signed in                     -> CLAIMED by them, then allowed, so
                                             signing in part-way through a
                                             guest session keeps the work and
                                             protects it from then on.
          * UNOWNED and the caller is a
            guest                         -> allowed. Guest sessions are a
                                             deliberate product feature and are
                                             protected only by the secrecy of
                                             their id; that is unchanged, not
                                             newly weakened.
        """
        session = self.get_session(session_id)
        if session.owner_id is not None:
            if session.owner_id != user_id:
                # Deliberately the same error an unknown id produces.
                raise SessionNotFoundError(session_id)
            return session
        if user_id is not None:
            session = session.model_copy(update={"owner_id": user_id})
            self._repository.save(session)
            logger.info("Session %s claimed by its first signed-in user", session_id)
        return session

    def skip_field(self, session_id: str, field_id: str) -> Session:
        """
        Record that the user declined to answer ONE field, and move on.

        Skippability is schema-driven, not a hardcoded list: a field may be
        skipped only when the interview registry marks it `required=False`.
        Those are the supplementary details a particular bank's form asks for
        (CKYC number, account number, district, monthly income) — real for that
        form, but not something every applicant has to hand. The core identity
        set (name, PAN, date of birth, mobile, declaration place) is
        `required=True` and can never be skipped, whichever form is active, so
        this cannot be used to bypass a form's genuine requirements.

        No value is written. Refusing to store 'skip' as the answer is the
        whole point: 'skip' is not a CKYC number, and it would otherwise flow
        into the canonical profile and onto the printed form.
        """
        session = self.get_session(session_id)
        field = self._forms.get_field(field_id)  # typed 404 for unknown ids
        if field.required:
            raise FieldNotSkippableError(field.display_name)

        if field_id not in session.skipped_fields:
            session.skipped_fields.append(field_id)
        # A skip supersedes any earlier rejected attempt; it stores no value.
        session.validation_errors.pop(field_id, None)

        self._refresh(session)
        session.touch()
        self._repository.save(session)
        logger.info("Session %s: field %s skipped", session_id, field_id)
        return session

    def unskip_field(self, session_id: str, field_id: str) -> Session:
        """Put a skipped field back in the queue so it can be answered."""
        session = self.get_session(session_id)
        if field_id in session.skipped_fields:
            session.skipped_fields.remove(field_id)
            self._refresh(session)
            session.touch()
            self._repository.save(session)
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
                # Answering un-skips: a field declined earlier is always
                # editable, and supplying it now must clear the skip so it
                # counts as genuinely answered.
                if field_id in session.skipped_fields:
                    session.skipped_fields.remove(field_id)
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

    def set_required_fields(
        self,
        session_id: str,
        field_ids: list[str] | None,
        conditional: list[ConditionalRequirement] | None = None,
    ) -> Session:
        """
        Scope this session to the ACTIVE primary form's required fields
        (Phase 13), then recompute derived state.

        Passing None restores the form registry's own required set. Unknown ids
        are ignored rather than rejected: a form schema may reference a field
        this build's registry doesn't carry, and that must never break a
        session. Answers are never touched — only what counts as "required".
        """
        session = self.get_session(session_id)
        known = {f.id for f in self._forms.get_all_fields()}
        if field_ids is None:
            session.required_field_ids = None
        else:
            session.required_field_ids = [f for f in field_ids if f in known]
        # Same tolerance for conditional rules: a schema may name a field this
        # build's registry doesn't carry, which must never break a session.
        session.conditional_required = [
            rule
            for rule in (conditional or [])
            if rule.field_id in known and rule.when_field in known
        ]
        self._refresh(session)
        session.touch()
        self._repository.save(session)
        logger.info(
            "Session %s scoped to %s required fields",
            session_id,
            "form-default" if field_ids is None else len(session.required_field_ids or []),
        )
        return session

    def _refresh(self, session: Session) -> None:
        """
        Recompute all derived fields from `answers` — the single place where
        progress %, completed fields, the current question, and interview
        status are calculated. Everything is driven by the schema; nothing is
        hardcoded.

        When the session is scoped to a primary form (Phase 13), THAT form's
        required set drives progress, completion and the next question — so an
        SBI or ICICI session is never measured against CVL's field list.
        """
        required = self._required_fields(session)
        # A skipped field is SETTLED: passed over when choosing the next
        # question and counted toward completion, while storing no value.
        # Without this the next question is always 'the first required
        # field without an answer', which is exactly the field the user
        # just declined - so it was asked again immediately, forever.
        skipped = set(session.skipped_fields)
        next_field = next(
            (f for f in required if f.id not in session.answers and f.id not in skipped),
            None,
        )
        answered_required = sum(
            1 for f in required if f.id in session.answers or f.id in skipped
        )

        session.current_field = next_field.id if next_field else None
        session.completed_fields = list(session.answers)

        # "No active questionnaire" is NOT "everything is done". A session
        # whose primary form was deleted has an empty required scope; reporting
        # that as 100% COMPLETED told the user their KYC was finished and
        # offered them a PDF for a form that no longer exists.
        no_active_form = (
            session.required_field_ids is not None and not session.required_field_ids
        )
        if no_active_form:
            session.progress_percentage = 0.0
            session.interview_status = InterviewStatus.NOT_STARTED
            return

        session.progress_percentage = (
            round((answered_required / len(required)) * 100, 1) if required else 100.0
        )
        # Completion is automatic (and reversible if a required answer is later
        # invalidated): COMPLETED exactly when no required field is missing.
        session.interview_status = (
            InterviewStatus.COMPLETED
            if next_field is None
            else InterviewStatus.IN_PROGRESS
        )

    def _required_fields(self, session: Session) -> tuple[KYCField, ...]:
        """
        The required fields for THIS session, in form order: the active primary
        form's set when one was selected, else the registry's own — plus any
        conditional field whose trigger currently holds.

        Evaluated on EVERY refresh, so answering "nationality = other" adds the
        free-text companion immediately, and supplying a PAN drops the
        PAN-exempt Proof of Identity question just as fast.
        """
        # `is not None`, deliberately: an EMPTY list means a primary form was
        # retired and there is no questionnaire, which must stay empty rather
        # than silently reverting to the registry's default required set.
        base = (
            set(session.required_field_ids)
            if session.required_field_ids is not None
            else {f.id for f in self._forms.get_required_fields()}
        )
        for rule in session.conditional_required:
            if rule.applies(session.answers):
                base.add(rule.field_id)
            else:
                base.discard(rule.field_id)
        # Iterate the registry (not the id set) so form order is preserved —
        # the interview must still ask in the printed order of the form.
        return tuple(f for f in self._forms.get_all_fields() if f.id in base)
