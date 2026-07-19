"""
Saved-conversation endpoints (Phase 12) — the /chats surface.

Every route requires a Bearer access token (guests use /knowledge/query
directly — same answers, nothing saved). Ownership is enforced inside
ChatService: another user's chat id is a plain 404.

    POST   /chats                    create a conversation
    GET    /chats?q=                 list / search conversations
    GET    /chats/{chat_id}          transcript (continue a previous chat)
    POST   /chats/{chat_id}/messages ask a question (RAG + multi-turn memory)
    PATCH  /chats/{chat_id}          rename
    DELETE /chats/{chat_id}          delete
"""

import logging

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import DomainError
from app.services.interview_service import InterviewService
from app.services.session_service import SessionService
from app.services.workflow_state import describe_session_state
from app.core.dependencies import (
    get_interview_service,
    get_session_service,
)
from app.core.dependencies import get_chat_service, get_current_user
from app.infrastructure.db.models import User
from app.schemas.chat import (
    AskRequest,
    AskResponse,
    ChatDetailResponse,
    ChatListResponse,
    ChatMessageResponse,
    ChatSummaryResponse,
    CreateChatRequest,
    DeleteChatResponse,
    RenameChatRequest,
)
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chats", tags=["Saved Conversations"])


@router.post(
    "",
    response_model=ChatSummaryResponse,
    status_code=201,
    summary="Create a saved conversation",
    responses={401: {"description": "Sign in to save conversations."}},
)
async def create_chat(
    body: CreateChatRequest,
    user: User = Depends(get_current_user),
    chats: ChatService = Depends(get_chat_service),
) -> ChatSummaryResponse:
    """Start a new saved conversation (title defaults to the first question)."""
    return ChatSummaryResponse.from_conversation(chats.create(user.id, body.title))


@router.get(
    "",
    response_model=ChatListResponse,
    summary="List / search saved conversations",
    responses={401: {"description": "Sign in to see your history."}},
)
async def list_chats(
    q: str | None = None,
    user: User = Depends(get_current_user),
    chats: ChatService = Depends(get_chat_service),
) -> ChatListResponse:
    """The caller's conversations, newest first; `q` searches titles + messages."""
    conversations = chats.list_conversations(user.id, q)
    return ChatListResponse(
        total=len(conversations),
        chats=[ChatSummaryResponse.from_conversation(c) for c in conversations],
    )


@router.get(
    "/{chat_id}",
    response_model=ChatDetailResponse,
    summary="Load a conversation's transcript",
    responses={401: {"description": "Not signed in."}, 404: {"description": "No such chat."}},
)
async def get_chat(
    chat_id: str,
    user: User = Depends(get_current_user),
    chats: ChatService = Depends(get_chat_service),
) -> ChatDetailResponse:
    """Full transcript, oldest first — powers 'continue previous chat'."""
    return ChatDetailResponse.from_conversation(chats.get(user.id, chat_id))


@router.post(
    "/{chat_id}/messages",
    response_model=AskResponse,
    summary="Ask a question inside a saved conversation",
    description=(
        "Persists the question, answers it through the Knowledge RAG engine "
        "(follow-ups are rewritten into standalone questions using the recent "
        "transcript — multi-turn memory), and persists the cited answer."
    ),
    responses={
        401: {"description": "Not signed in."},
        404: {"description": "No such chat."},
        409: {"description": "Knowledge index is empty."},
        503: {"description": "RAG stack not installed."},
    },
)
async def ask(
    chat_id: str,
    body: AskRequest,
    user: User = Depends(get_current_user),
    chats: ChatService = Depends(get_chat_service),
    sessions: SessionService = Depends(get_session_service),
    interview: InterviewService = Depends(get_interview_service),
) -> AskResponse:
    """One persisted RAG turn (embedding + LLM run off the event loop)."""
    # The caller's OWN session, through the same ownership check every
    # session endpoint uses. Not theirs (or absent) yields no state, and
    # the engine says so honestly rather than guessing.
    workflow_state: str | None = None
    if body.session_id:
        try:
            sessions.assert_owner(body.session_id, user.id)
            workflow_state = describe_session_state(
                body.session_id, sessions, interview
            )
        except DomainError:
            workflow_state = None
    user_message, assistant_message, _ = await run_in_threadpool(
        chats.ask, user.id, chat_id, body.question, workflow_state
    )
    return AskResponse(
        chat_id=chat_id,
        user_message=ChatMessageResponse.from_message(user_message),
        assistant_message=ChatMessageResponse.from_message(assistant_message),
    )


@router.patch(
    "/{chat_id}",
    response_model=ChatSummaryResponse,
    summary="Rename a conversation",
    responses={401: {"description": "Not signed in."}, 404: {"description": "No such chat."}},
)
async def rename_chat(
    chat_id: str,
    body: RenameChatRequest,
    user: User = Depends(get_current_user),
    chats: ChatService = Depends(get_chat_service),
) -> ChatSummaryResponse:
    """Give the conversation a new title."""
    return ChatSummaryResponse.from_conversation(chats.rename(user.id, chat_id, body.title))


@router.delete(
    "/{chat_id}",
    response_model=DeleteChatResponse,
    summary="Delete a conversation",
    responses={401: {"description": "Not signed in."}, 404: {"description": "No such chat."}},
)
async def delete_chat(
    chat_id: str,
    user: User = Depends(get_current_user),
    chats: ChatService = Depends(get_chat_service),
) -> DeleteChatResponse:
    """Delete the conversation and its messages permanently."""
    chats.delete(user.id, chat_id)
    return DeleteChatResponse(chat_id=chat_id)
