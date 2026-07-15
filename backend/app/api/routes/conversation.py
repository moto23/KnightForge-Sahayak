"""
AI conversation endpoints (Phase 5).

Thin HTTP layer over ConversationService. Flow control, validation, and
completion stay with the deterministic Session Engine underneath; these routes
only add natural language on top. Every response answers even when OpenAI is
down (`ai_generated: false` marks fallback phrasing).
"""

import logging

from fastapi import APIRouter, Depends

from app.core.dependencies import get_conversation_service
from app.schemas.conversation import (
    ExplainRequest,
    ExplainResponse,
    ExtractedAnswerModel,
    ExtractRequest,
    ExtractResponse,
    ReplyRequest,
    ReplyResponse,
    StartConversationRequest,
    StartConversationResponse,
)
from app.schemas.session import SessionResponse
from app.services.conversation_service import ConversationService, ExtractedAnswer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversation", tags=["AI Conversation"])


def _extraction_model(extraction: ExtractedAnswer | None) -> ExtractedAnswerModel | None:
    if extraction is None:
        return None
    return ExtractedAnswerModel(
        field_id=extraction.field_id,
        value=extraction.value,
        confidence=extraction.confidence,
        intent=extraction.intent,
        ai_generated=extraction.ai_generated,
    )


@router.post(
    "/start",
    response_model=StartConversationResponse,
    status_code=201,
    summary="Start a conversational interview",
    description=(
        "Creates a session and returns the first question phrased "
        "conversationally in the chosen language (english/hinglish/hindi)."
    ),
)
async def start_conversation(
    request: StartConversationRequest,
    conversation: ConversationService = Depends(get_conversation_service),
) -> StartConversationResponse:
    """Create a session and greet the user with the first question."""
    opening = conversation.start_conversation(request.language)
    return StartConversationResponse(
        session_id=opening.session.session_id,
        language=request.language,
        message=opening.message,
        ai_generated=opening.ai_generated,
        question=opening.question,
        session=SessionResponse.from_session(opening.session),
    )


@router.post(
    "/reply",
    response_model=ReplyResponse,
    summary="Send a user message",
    description=(
        "One conversational turn: the AI extracts an answer from the message, "
        "the deterministic engine validates and stores it, and the AI phrases "
        "the outcome (next question, correction, or completion)."
    ),
    responses={404: {"description": "Session not found."}},
)
async def reply(
    request: ReplyRequest,
    conversation: ConversationService = Depends(get_conversation_service),
) -> ReplyResponse:
    """Handle one user message end-to-end."""
    result = conversation.reply(request.session_id, request.message, request.language)
    return ReplyResponse(
        session_id=result.session.session_id,
        message=result.message,
        ai_generated=result.ai_generated,
        intent=result.intent,
        extraction=_extraction_model(result.extraction),
        accepted=result.accepted,
        validation=result.validation,
        next_question=result.next_question,
        interview_status=result.session.interview_status,
        progress_percentage=result.session.progress_percentage,
    )


@router.post(
    "/explain",
    response_model=ExplainResponse,
    summary="Explain a field",
    description=(
        "Plain-language explanation of a field: what it is, why the bank needs "
        "it, and the expected format. Omit field_id for the current question."
    ),
    responses={404: {"description": "Session or field not found."}},
)
async def explain(
    request: ExplainRequest,
    conversation: ConversationService = Depends(get_conversation_service),
) -> ExplainResponse:
    """Explain one field of the KYC form."""
    explanation = conversation.explain_field(
        request.session_id, request.field_id, request.language
    )
    return ExplainResponse(
        session_id=request.session_id,
        field_id=explanation.field.id if explanation.field else None,
        message=explanation.message,
        ai_generated=explanation.ai_generated,
    )


@router.post(
    "/extract",
    response_model=ExtractResponse,
    summary="Extract a structured answer from natural language",
    description=(
        "Extraction only — returns the normalized machine value the AI (or the "
        "deterministic fallback) read from the message. Nothing is validated "
        "or stored; use /conversation/reply for the full loop."
    ),
    responses={404: {"description": "Session or field not found."}},
)
async def extract(
    request: ExtractRequest,
    conversation: ConversationService = Depends(get_conversation_service),
) -> ExtractResponse:
    """Turn free text into a structured, normalized answer candidate."""
    extraction = conversation.extract_answer(
        request.session_id, request.message, request.field_id, request.language
    )
    return ExtractResponse(
        session_id=request.session_id,
        extraction=_extraction_model(extraction),
    )
