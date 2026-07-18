"""
Session & interview endpoints — the conversational KYC flow, fully deterministic.

Thin HTTP layer over InterviewService/SessionService: routes translate DTOs and
delegate. No flow logic, no validation, no if/else on field types lives here.
Unknown session ids and field ids surface as typed 404s through the global
DomainError handlers.
"""

import logging

from fastapi import APIRouter, Depends

from app.core.dependencies import (
    get_conversation_service,
    get_interview_service,
    get_session_service,
)
from app.schemas.session import (
    ClearAnswerResponse,
    CreateSessionResponse,
    DeleteSessionResponse,
    NextQuestionResponse,
    ProgressResponse,
    SessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from app.services.conversation_service import ConversationService
from app.services.interview_service import InterviewService
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/session", tags=["Session & Interview"])


@router.post(
    "",
    response_model=CreateSessionResponse,
    status_code=201,
    summary="Create a session (start the interview)",
    description="Creates a new interview session and returns the first question.",
)
async def create_session(
    interview: InterviewService = Depends(get_interview_service),
) -> CreateSessionResponse:
    """Start a new KYC interview session."""
    session, first_question = interview.start_interview()
    return CreateSessionResponse(
        session=SessionResponse.from_session(session),
        next_question=first_question,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get a session",
    responses={404: {"description": "Session not found."}},
)
async def get_session(
    session_id: str,
    sessions: SessionService = Depends(get_session_service),
) -> SessionResponse:
    """Return the full current state of a session."""
    return SessionResponse.from_session(sessions.get_session(session_id))


@router.delete(
    "/{session_id}",
    response_model=DeleteSessionResponse,
    summary="Delete a session",
    responses={404: {"description": "Session not found."}},
)
async def delete_session(
    session_id: str,
    sessions: SessionService = Depends(get_session_service),
    conversation: ConversationService = Depends(get_conversation_service),
) -> DeleteSessionResponse:
    """Delete a session, all its (in-memory) answers, and its transcript."""
    sessions.delete_session(session_id)
    conversation.forget(session_id)
    return DeleteSessionResponse(session_id=session_id, deleted=True)


@router.post(
    "/{session_id}/answer",
    response_model=SubmitAnswerResponse,
    summary="Submit an answer",
    description=(
        "Validates the answer with the Validation Engine. Valid answers are "
        "stored; invalid ones are recorded separately with the reason. The "
        "response includes refreshed progress and the next question."
    ),
    responses={404: {"description": "Session or field not found."}},
)
async def submit_answer(
    session_id: str,
    request: SubmitAnswerRequest,
    interview: InterviewService = Depends(get_interview_service),
) -> SubmitAnswerResponse:
    """Answer one field; validation + progress + next question in one call."""
    outcome = interview.submit_answer(session_id, request.field_id, request.value)
    return SubmitAnswerResponse(
        field_id=request.field_id,
        accepted=outcome.result.valid,
        result=outcome.result,
        session=SessionResponse.from_session(outcome.session),
        next_question=outcome.next_question,
    )


@router.delete(
    "/{session_id}/answer/{field_id}",
    response_model=ClearAnswerResponse,
    summary="Clear one answer (prefill rollback)",
    description=(
        "Removes a field's stored answer (or invalid attempt) so it becomes "
        "PENDING again, then recomputes progress, next question, and interview "
        "status. Used to roll back AI-prefilled values when their source "
        "document is deleted — the session never keeps data from a deleted "
        "document. Idempotent for already-empty fields."
    ),
    responses={404: {"description": "Session or field not found."}},
)
async def clear_answer(
    session_id: str,
    field_id: str,
    sessions: SessionService = Depends(get_session_service),
) -> ClearAnswerResponse:
    """Un-answer one field; all derived state is recomputed by the service."""
    session = sessions.clear_answer(session_id, field_id)
    return ClearAnswerResponse(
        field_id=field_id,
        cleared=True,
        session=SessionResponse.from_session(session),
    )


@router.get(
    "/{session_id}/next",
    response_model=NextQuestionResponse,
    summary="Get the next question",
    description="First missing required field in form order — never hardcoded.",
    responses={404: {"description": "Session not found."}},
)
async def next_question(
    session_id: str,
    interview: InterviewService = Depends(get_interview_service),
) -> NextQuestionResponse:
    """Return metadata for the next field the user should answer."""
    session, question = interview.next_question(session_id)
    progress = interview.current_progress(session_id)
    return NextQuestionResponse(
        session_id=session.session_id,
        completed=question is None,
        question=question,
        remaining_required=len(progress.pending_required_fields),
    )


@router.get(
    "/{session_id}/progress",
    response_model=ProgressResponse,
    summary="Get interview progress",
    responses={404: {"description": "Session not found."}},
)
async def get_progress(
    session_id: str,
    interview: InterviewService = Depends(get_interview_service),
) -> ProgressResponse:
    """Progress %, completed/pending/remaining-required fields — all computed."""
    report = interview.current_progress(session_id)
    return ProgressResponse(
        session_id=report.session_id,
        interview_status=report.interview_status,
        progress_percentage=report.progress_percentage,
        total_fields=report.total_fields,
        required_fields=report.required_fields,
        answered_fields=report.answered_fields,
        completed_required_fields=report.completed_required_fields,
        pending_required_fields=list(report.pending_required_fields),
        invalid_fields=list(report.invalid_fields),
    )
