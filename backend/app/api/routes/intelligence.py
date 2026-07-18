"""
Universal Document Intelligence endpoints (Phase 11) — the /intelligence surface.

Thin layer over DocumentIntelligenceService, zero logic in routes:

    POST /intelligence/process              — classify + extract + merge one document
    GET  /intelligence/profile/{session_id} — the session's unified canonical profile
    POST /intelligence/resolve              — resolve one field conflict

Failures surface as typed DomainErrors through the global handlers:
404 document_not_found / session_not_found / conflict_not_found,
422 document_unreadable / invalid_conflict_resolution, 502 ocr_failed,
500 document_schemas_missing.
"""

import logging

from fastapi import APIRouter, Depends

from app.core.dependencies import (
    get_document_intelligence_service,
    get_upload_history_service,
)
from app.schemas.intelligence import (
    ConflictResolveRequest,
    IntelligenceProcessRequest,
    IntelligenceProcessResponse,
    PrimaryFormRequest,
    UnifiedProfileResponse,
)
from app.services.document_intelligence_service import DocumentIntelligenceService
from app.services.upload_history_service import UploadHistoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["Universal Document Intelligence"])


@router.post(
    "/process",
    response_model=IntelligenceProcessResponse,
    summary="Classify a document and merge it into the session's unified profile",
    description=(
        "Runs the schema-driven pipeline for one uploaded document: document "
        "classification → schema load → OCR (cached) → canonical field "
        "extraction → merge engine → conflict detection → validated session "
        "prefill. The SAME pipeline serves every supported form — only the "
        "loaded schema differs."
    ),
    responses={
        404: {"description": "Document or session not found."},
        422: {"description": "Document is unreadable (corrupt/blank)."},
        500: {"description": "No document schemas installed."},
        502: {"description": "The OCR engine failed."},
    },
)
async def process_document(
    body: IntelligenceProcessRequest,
    service: DocumentIntelligenceService = Depends(get_document_intelligence_service),
    history: UploadHistoryService = Depends(get_upload_history_service),
) -> IntelligenceProcessResponse:
    """Process one document through the universal pipeline (idempotent)."""
    report = service.process_document(body.document_id, body.session_id)
    response = IntelligenceProcessResponse.from_report(report)
    try:
        # Phase 13 journal: record the AI-detected type + mark as processed.
        history.mark_processed(
            body.document_id, detected_type=response.document.document_type.label
        )
    except Exception:  # noqa: BLE001
        logger.warning("Upload history update failed for %s", body.document_id)
    return response


@router.get(
    "/profile/{session_id}",
    response_model=UnifiedProfileResponse,
    summary="Get the session's unified canonical KYC profile",
    description=(
        "Returns the merged profile built from every processed document: "
        "detected document types, merged canonical fields with provenance, "
        "open conflict cards, and which interview answers were auto-applied. "
        "Always re-synced — deleted documents drop out automatically."
    ),
    responses={404: {"description": "Session not found."}},
)
async def get_profile(
    session_id: str,
    service: DocumentIntelligenceService = Depends(get_document_intelligence_service),
) -> UnifiedProfileResponse:
    """Return the re-synced unified profile for a session."""
    report = service.get_profile(session_id)
    return UnifiedProfileResponse.from_report(report)


@router.post(
    "/primary-form",
    response_model=UnifiedProfileResponse,
    summary="Select the session's PRIMARY form (the final output)",
    description=(
        "Records which KYC form this session will generate as its final PDF. "
        "Supporting documents (PAN, Aadhaar, passport…) are only evidence "
        "used to autofill it — they never change the output form."
    ),
    responses={
        404: {"description": "Session not found."},
        422: {"description": "Not an installed KYC form schema."},
    },
)
async def set_primary_form(
    body: PrimaryFormRequest,
    service: DocumentIntelligenceService = Depends(get_document_intelligence_service),
) -> UnifiedProfileResponse:
    """Store the primary-form choice and return the re-synced profile."""
    report = service.set_primary_form(body.session_id, body.form_id)
    return UnifiedProfileResponse.from_report(report)


@router.post(
    "/resolve",
    response_model=UnifiedProfileResponse,
    summary="Resolve a field conflict by choosing the correct value",
    description=(
        "Records the user's choice for one conflicted canonical field (by "
        "source document or exact candidate value), applies it to the "
        "interview session through the normal validated answer path, and "
        "returns the re-merged profile. Values are never invented — the "
        "choice must be one of the detected candidates."
    ),
    responses={
        404: {"description": "Session not found, or no such conflict."},
        422: {"description": "The chosen value/document is not a candidate."},
    },
)
async def resolve_conflict(
    body: ConflictResolveRequest,
    service: DocumentIntelligenceService = Depends(get_document_intelligence_service),
) -> UnifiedProfileResponse:
    """Record a conflict resolution and return the updated profile."""
    report = service.resolve_conflict(
        body.session_id, body.canonical_id, body.document_id, body.value
    )
    return UnifiedProfileResponse.from_report(report)
