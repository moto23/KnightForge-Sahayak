"""
Knowledge RAG endpoints (Phase 10) — the /knowledge surface.

Thin layer over KnowledgeService, zero logic in routes:

    POST /knowledge/index   — (re)build the vector index from the corpus
    POST /knowledge/query   — retrieve + generate a cited, grounded answer
    GET  /knowledge/status  — engine health: index size, model, config

Failures surface as typed DomainErrors through the global handlers:
503 knowledge_unavailable (RAG stack not installed), 404
knowledge_corpus_missing (no documents to index), 409 knowledge_index_empty
(query before index). A low-similarity question is NOT an error — it returns
200 with an honest "I don't know" answer and confident=false.

Blocking work (embedding, Chroma, the OpenAI call) runs in the threadpool via
`run_in_threadpool`, so a long index rebuild never blocks the event loop.
"""

import logging

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.core.exceptions import DomainError
from app.core.rate_limit import knowledge_limiter, limit
from app.infrastructure.db.models import User
from app.services.interview_service import InterviewService
from app.services.session_service import SessionService
from app.services.workflow_state import describe_session_state
from app.core.dependencies import (
    get_interview_service,
    get_optional_user,
    get_session_service,
)
from app.core.dependencies import get_knowledge_service
from app.schemas.knowledge import (
    KnowledgeIndexResponse,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeStatusResponse,
)
from app.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["Knowledge RAG"])


@router.post(
    "/index",
    dependencies=[Depends(limit(knowledge_limiter))],
    response_model=KnowledgeIndexResponse,
    summary="Build (or rebuild) the knowledge index",
    description=(
        "Loads every official document from the knowledge corpus directory, "
        "splits them into semantic chunks with metadata (document name, page "
        "number, source), embeds them with the local SentenceTransformer "
        "model, and atomically rebuilds the ChromaDB index. Idempotent — safe "
        "to re-run whenever the corpus changes. The first run downloads the "
        "embedding model, so it can take a minute."
    ),
    responses={
        404: {"description": "No documents found in the corpus directory."},
        503: {"description": "chromadb / sentence-transformers not installed."},
    },
)
async def build_index(
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeIndexResponse:
    report = await run_in_threadpool(knowledge.index)
    return KnowledgeIndexResponse.from_report(report)


@router.post(
    "/query",
    dependencies=[Depends(limit(knowledge_limiter))],
    response_model=KnowledgeQueryResponse,
    summary="Ask a question grounded in the indexed documents",
    description=(
        "Retrieves the most relevant chunks for the question and generates an "
        "answer FROM THAT CONTEXT ONLY, with citations to the source "
        "documents. If no chunk clears the similarity floor, the reply is an "
        "honest \"I don't know\" (confident=false) — the engine never guesses. "
        "Without an OpenAI key, answers degrade to cited verbatim excerpts."
    ),
    responses={
        409: {"description": "The index is empty — run POST /knowledge/index first."},
        503: {"description": "chromadb / sentence-transformers not installed."},
    },
)
async def query_knowledge(
    payload: KnowledgeQueryRequest,
    knowledge: KnowledgeService = Depends(get_knowledge_service),
    sessions: SessionService = Depends(get_session_service),
    interview: InterviewService = Depends(get_interview_service),
    user: User | None = Depends(get_optional_user),
) -> KnowledgeQueryResponse:
    # Read the caller's OWN session state, through the same ownership check
    # every other session endpoint uses. A session that is not theirs (or
    # not there) simply yields no state, and the engine says so honestly
    # rather than guessing.
    workflow_state: str | None = None
    if payload.session_id:
        try:
            sessions.assert_owner(
                payload.session_id, user.id if user else None
            )
            workflow_state = describe_session_state(
                payload.session_id, sessions, interview
            )
        except DomainError:
            workflow_state = None
    answer = await run_in_threadpool(
        knowledge.query, payload.question, payload.top_k, workflow_state
    )
    return KnowledgeQueryResponse.from_answer(answer)


@router.get(
    "/status",
    response_model=KnowledgeStatusResponse,
    summary="Knowledge engine status",
    description=(
        "Whether the RAG stack is installed and indexed, how many documents/"
        "chunks are searchable, and the active configuration (embedding "
        "model, chunking, retrieval parameters). Never errors — a missing "
        "install reports dependencies_installed=false instead."
    ),
)
async def knowledge_status(
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeStatusResponse:
    status = await run_in_threadpool(knowledge.status)
    return KnowledgeStatusResponse.from_status(status)
