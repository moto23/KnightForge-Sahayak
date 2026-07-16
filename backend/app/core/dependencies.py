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

from app.core.config import settings
from app.infrastructure.ocr.pymupdf_inspector import PyMuPdfInspector
from app.infrastructure.ocr.tesseract_ocr_provider import TesseractOCRProvider
from app.infrastructure.repositories.in_memory_conversation_repository import (
    InMemoryConversationRepository,
)
from app.infrastructure.repositories.in_memory_document_repository import (
    InMemoryDocumentRepository,
)
from app.infrastructure.repositories.in_memory_session_repository import (
    InMemorySessionRepository,
)
from app.infrastructure.repositories.in_memory_understanding_repository import (
    InMemoryDocumentUnderstandingRepository,
)
from app.infrastructure.storage.local_storage_adapter import LocalStorageAdapter
from app.services.ai_service import AIService
from app.services.conversation_service import ConversationService
from app.services.document_analysis_service import DocumentAnalysisService
from app.services.document_understanding_service import DocumentUnderstandingService
from app.services.extraction_engine import extraction_engine
from app.services.form_service import FormService, form_service
from app.services.form_validation_service import (
    FormValidationService,
    form_validation_service,
)
from app.services.interview_service import InterviewService
from app.services.ocr_service import OCRService
from app.services.session_prefill_service import SessionPrefillService
from app.services.session_service import SessionService
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
