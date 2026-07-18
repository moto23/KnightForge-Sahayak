"""
Shared FastAPI dependency providers — the application's composition root.

Central place where routes obtain their collaborators via `Depends()`. Routes
never construct services themselves — they declare what they need and this
module provides it, which keeps wiring in one spot and makes overriding
dependencies in tests trivial (app.dependency_overrides).

This is also the ONLY module that binds abstractions to concrete adapters
(SessionRepository -> InMemorySessionRepository). Services stay ignorant of
which storage backs them, so swapping to PostgreSQL later is a one-line change
here.
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthRequiredError
from app.core.security import decode_access_token
from app.infrastructure.db import get_db
from app.infrastructure.db.models import User
from app.infrastructure.intelligence import FileSystemSchemaSource
from app.infrastructure.knowledge import (
    ChromaVectorStore,
    FileSystemCorpusLoader,
    SentenceTransformerEmbedder,
)
from app.infrastructure.ocr.pymupdf_inspector import PyMuPdfInspector
from app.infrastructure.ocr.tesseract_ocr_provider import TesseractOCRProvider
from app.infrastructure.pdf.coordinate_overlay_pdf_generator import (
    CoordinateOverlayPDFGenerator,
)
from app.infrastructure.repositories.in_memory_conversation_repository import (
    InMemoryConversationRepository,
)
from app.infrastructure.repositories.in_memory_document_repository import (
    InMemoryDocumentRepository,
)
from app.infrastructure.repositories.in_memory_generated_pdf_repository import (
    InMemoryGeneratedPdfRepository,
)
from app.infrastructure.repositories.in_memory_profile_repository import (
    InMemoryProfileRepository,
)
from app.infrastructure.repositories.in_memory_session_repository import (
    InMemorySessionRepository,
)
from app.infrastructure.repositories.in_memory_understanding_repository import (
    InMemoryDocumentUnderstandingRepository,
)
from app.infrastructure.storage.local_storage_adapter import LocalStorageAdapter
from app.services.ai_service import AIService
from app.services.auth_service import AuthService
from app.services.chat_service import ChatService
from app.services.conflict_service import conflict_service
from app.services.conversation_service import ConversationService
from app.services.coordinate_mapper import CoordinateMapper
from app.services.document_analysis_service import DocumentAnalysisService
from app.services.document_classifier import document_classifier
from app.services.document_intelligence_service import DocumentIntelligenceService
from app.services.semantic_extractor import SemanticExtractorService
from app.services.document_understanding_service import DocumentUnderstandingService
from app.services.field_mapper import field_mapper
from app.services.merge_service import merge_service
from app.services.extraction_engine import extraction_engine
from app.services.form_service import FormService, form_service
from app.services.form_validation_service import (
    FormValidationService,
    form_validation_service,
)
from app.services.interview_service import InterviewService
from app.services.knowledge_service import KnowledgeService
from app.services.ocr_service import OCRService
from app.services.pdf_generation_service import PDFGenerationService
from app.services.session_prefill_service import SessionPrefillService
from app.services.session_service import SessionService
from app.services.upload_history_service import UploadHistoryService
from app.services.upload_service import UploadService

# --------------------------------------------------------------------------- #
# Singletons composed once at import time. The repositories MUST be single
# shared instances — they hold all live sessions/transcripts in memory.
# --------------------------------------------------------------------------- #
_session_repository = InMemorySessionRepository()
_conversation_repository = InMemoryConversationRepository()
_document_repository = InMemoryDocumentRepository()
_file_storage = LocalStorageAdapter(root=settings.UPLOAD_DIR)
session_service = SessionService(repository=_session_repository)
interview_service = InterviewService(sessions=session_service)
ai_service = AIService()
conversation_service = ConversationService(
    interview=interview_service,
    transcript=_conversation_repository,
    ai=ai_service,
)
# Phase 6: swap LocalStorageAdapter for an S3 adapter here — one line — and the
# whole upload pipeline moves to the cloud untouched.
upload_service = UploadService(repository=_document_repository, storage=_file_storage)

# --------------------------------------------------------------------------- #
# Phase 7 — Intelligent Document Understanding Pipeline.
# The ONLY place Tesseract (and PyMuPDF/Pillow) are bound to their ports:
# swap TesseractOCRProvider for a cloud OCR adapter here and nothing else
# in the codebase changes.
# --------------------------------------------------------------------------- #
_ocr_provider = TesseractOCRProvider()
_document_inspector = PyMuPdfInspector()
_understanding_repository = InMemoryDocumentUnderstandingRepository()
document_understanding_service = DocumentUnderstandingService(
    uploads=upload_service,
    analysis=DocumentAnalysisService(inspector=_document_inspector),
    ocr=OCRService(provider=_ocr_provider, inspector=_document_inspector),
    extraction=extraction_engine,
    prefill=SessionPrefillService(sessions=session_service),
    repository=_understanding_repository,
)

# --------------------------------------------------------------------------- #
# Phase 8 — Smart PDF Generation Engine.
# The ONLY place the PDF renderer is bound to its port: swap
# CoordinateOverlayPDFGenerator for a ReportLab/pypdf (or AcroForm) adapter
# here and nothing else in the codebase changes. Coordinates live in the
# external JSON map — never in Python.
# --------------------------------------------------------------------------- #
_pdf_generator = CoordinateOverlayPDFGenerator()
_generated_pdf_repository = InMemoryGeneratedPdfRepository()
pdf_generation_service = PDFGenerationService(
    sessions=session_service,
    mapper=CoordinateMapper(map_path=settings.PDF_COORDINATE_MAP_PATH),
    generator=_pdf_generator,
    repository=_generated_pdf_repository,
)


# --------------------------------------------------------------------------- #
# Phase 10 — Knowledge RAG Engine.
# The ONLY place SentenceTransformers and ChromaDB are bound to their ports:
# swap in an API embedder or a pgvector store here and nothing else changes.
# Completely independent of the OCR/session/upload/PDF services above — the
# knowledge engine shares only the AIService for answer phrasing.
# --------------------------------------------------------------------------- #
knowledge_service = KnowledgeService(
    loader=FileSystemCorpusLoader(),
    embedder=SentenceTransformerEmbedder(model_name=settings.KNOWLEDGE_EMBEDDING_MODEL),
    store=ChromaVectorStore(
        db_path=settings.KNOWLEDGE_DB_DIR,
        collection_name=settings.KNOWLEDGE_COLLECTION,
    ),
    ai=ai_service,
    # Probed once here — the composition root is the only layer that may know
    # which concrete adapters (and therefore which libraries) are in play.
    dependencies_installed=(
        SentenceTransformerEmbedder.dependencies_installed()
        and ChromaVectorStore.dependencies_installed()
    ),
)


# --------------------------------------------------------------------------- #
# Phase 11 — Universal Document Intelligence.
# ONE reusable pipeline for every supported document: classification and
# extraction are driven entirely by the JSON schemas in backend/schemas/ —
# adding a new bank's form is a new JSON file, never new wiring or new code.
# --------------------------------------------------------------------------- #
_schema_source = FileSystemSchemaSource()
_profile_repository = InMemoryProfileRepository()
semantic_extractor_service = SemanticExtractorService(ai=ai_service)

document_intelligence_service = DocumentIntelligenceService(
    uploads=upload_service,
    understanding=document_understanding_service,  # reuses cached analysis + OCR
    schemas=_schema_source,
    classifier=document_classifier,
    mapper=field_mapper,
    merge=merge_service,
    conflicts=conflict_service,
    sessions=session_service,
    repository=_profile_repository,
    semantic=semantic_extractor_service,  # hybrid: Gemini pass, graceful fallback
)


def get_form_service() -> FormService:
    """Provide the shared, stateless FormService instance."""
    return form_service


def get_form_validation_service() -> FormValidationService:
    """Provide the shared, stateless FormValidationService instance."""
    return form_validation_service


def get_session_service() -> SessionService:
    """Provide the shared SessionService (backed by the in-memory repository)."""
    return session_service


def get_interview_service() -> InterviewService:
    """Provide the shared InterviewService (interview flow orchestrator)."""
    return interview_service


def get_conversation_service() -> ConversationService:
    """Provide the shared ConversationService (AI phrasing over the engine)."""
    return conversation_service


def get_upload_service() -> UploadService:
    """Provide the shared UploadService (document upload pipeline)."""
    return upload_service


def get_document_understanding_service() -> DocumentUnderstandingService:
    """Provide the shared DocumentUnderstandingService (OCR + extraction pipeline)."""
    return document_understanding_service


def get_pdf_generation_service() -> PDFGenerationService:
    """Provide the shared PDFGenerationService (filled-KYC PDF engine)."""
    return pdf_generation_service


def get_knowledge_service() -> KnowledgeService:
    """Provide the shared KnowledgeService (Knowledge RAG engine)."""
    return knowledge_service


def get_document_intelligence_service() -> DocumentIntelligenceService:
    """Provide the shared DocumentIntelligenceService (universal pipeline)."""
    return document_intelligence_service


# --------------------------------------------------------------------------- #
# Phase 12 — Authentication + Conversation Persistence.
# Unlike the singletons above, these services are built PER REQUEST around a
# scoped SQLAlchemy session (get_db). Auth guards exist ONLY on /auth/me and
# /chats/* — every earlier endpoint stays guest-accessible by construction.
# --------------------------------------------------------------------------- #

# auto_error=False so a missing header raises OUR typed 401 (consistent
# error envelope) instead of FastAPI's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    """Provide an AuthService bound to this request's DB session."""
    return AuthService(db)


def get_chat_service(db: Session = Depends(get_db)) -> ChatService:
    """Provide a ChatService bound to this request's DB session.

    Reuses the shared KnowledgeService and AIService singletons — the chat
    layer wraps the RAG engine, it never re-implements it.
    """
    return ChatService(db, knowledge=knowledge_service, ai=ai_service)


def get_upload_history_service(db: Session = Depends(get_db)) -> UploadHistoryService:
    """Provide an UploadHistoryService bound to this request's DB session."""
    return UploadHistoryService(db)


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Resolve the Bearer token to a User when present — None for guests.

    Used by endpoints that stay guest-accessible (Phase 13 upload history):
    a valid token associates the action with the account, anything else
    (missing/expired/bad token) degrades silently to guest instead of 401.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        user_id = decode_access_token(credentials.credentials)
    except Exception:  # expired/garbled token — guest, not an error
        return None
    return db.get(User, user_id)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Authorization guard: resolve the Bearer access token to a live User.

    Raises the typed 401 (auth_required) when the header is missing, the JWT
    is invalid/expired, or the account no longer exists.
    """
    if credentials is None or not credentials.credentials:
        raise AuthRequiredError()
    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if user is None:
        raise AuthRequiredError("This account no longer exists.")
    return user
