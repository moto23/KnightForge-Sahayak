"""
Document-understanding endpoints (Phase 7) — the /ocr surface.

Thin layer over DocumentUnderstandingService, zero logic in routes:

    POST /ocr                — run analysis + OCR; return statistics (no raw text)
    POST /ocr/extract        — run the pipeline; return the structured extraction
    POST /ocr/prefill        — apply accepted fields to an interview session
    GET  /ocr/{document_id}  — cached results for an already-processed document

Failures surface as typed DomainErrors through the global handlers:
404 document_not_found / document_not_processed / session_not_found,
422 document_unreadable, 502 ocr_failed.
"""

import logging

from fastapi import APIRouter, Depends

from app.core.rate_limit import ai_limiter, limit
from app.core.dependencies import (
    get_document_understanding_service,
    get_upload_history_service,
)
from app.schemas.ocr import (
    OCRExtractResponse,
    OCRProcessRequest,
    OCRRunResponse,
    PrefillRequest,
    PrefillResponse,
)
from app.services.document_understanding_service import DocumentUnderstandingService
from app.services.upload_history_service import UploadHistoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ocr", tags=["Document Understanding"])


def _mark_ocr_history(
    history: UploadHistoryService, document_id: str, *, ok: bool
) -> None:
    """Best-effort Phase 13 journal update — never fails the OCR request."""
    try:
        history.mark_ocr(document_id, ok=ok)
    except Exception:  # noqa: BLE001
        logger.warning("Upload history OCR update failed for %s", document_id)


@router.post(
    "",
    dependencies=[Depends(limit(ai_limiter))],
    response_model=OCRRunResponse,
    summary="Analyze and OCR an uploaded document",
    description=(
        "Runs document detection (type, pages, quality) and OCR over a "
        "previously uploaded document, then caches the result. Returns the "
        "analysis verdict and OCR statistics — raw OCR text is never exposed."
    ),
    responses={
        404: {"description": "Document not found."},
        422: {"description": "Document is unreadable (corrupt/blank)."},
        502: {"description": "The OCR engine failed."},
    },
)
async def run_ocr(
    body: OCRProcessRequest,
    pipeline: DocumentUnderstandingService = Depends(get_document_understanding_service),
    history: UploadHistoryService = Depends(get_upload_history_service),
) -> OCRRunResponse:
    """Process one document through analysis + OCR (cached, idempotent)."""
    try:
        record = pipeline.process(body.document_id, force=body.force)
    except Exception:
        _mark_ocr_history(history, body.document_id, ok=False)
        raise
    _mark_ocr_history(history, body.document_id, ok=True)
    return OCRRunResponse.from_domain(record)


@router.post(
    "/extract",
    dependencies=[Depends(limit(ai_limiter))],
    response_model=OCRExtractResponse,
    summary="Extract structured KYC fields from a document",
    description=(
        "Runs the full understanding pipeline (analysis → OCR → extraction → "
        "confidence scoring → validation) and returns the structured KYC "
        "fields. Every field carries its value, confidence, source, and the "
        "deterministic Validation Engine's verdict."
    ),
    responses={
        404: {"description": "Document not found."},
        422: {"description": "Document is unreadable (corrupt/blank)."},
        502: {"description": "The OCR engine failed."},
    },
)
async def extract_fields(
    body: OCRProcessRequest,
    pipeline: DocumentUnderstandingService = Depends(get_document_understanding_service),
    history: UploadHistoryService = Depends(get_upload_history_service),
) -> OCRExtractResponse:
    """Return the structured extraction for one document (cached, idempotent)."""
    try:
        record = pipeline.process(body.document_id, force=body.force)
    except Exception:
        _mark_ocr_history(history, body.document_id, ok=False)
        raise
    _mark_ocr_history(history, body.document_id, ok=True)
    return OCRExtractResponse.from_domain(record)


@router.post(
    "/prefill",
    dependencies=[Depends(limit(ai_limiter))],
    response_model=PrefillResponse,
    summary="Prefill an interview session from a document",
    description=(
        "Writes ONLY high-confidence, validation-passing extracted fields into "
        "an existing interview session; uncertain or invalid values are left "
        "unanswered for the interview to ask. User-provided answers are never "
        "overwritten unless `overwrite` is explicitly true."
    ),
    responses={
        404: {"description": "Document or session not found."},
        422: {"description": "Document is unreadable (corrupt/blank)."},
        502: {"description": "The OCR engine failed."},
    },
)
async def prefill_session(
    body: PrefillRequest,
    pipeline: DocumentUnderstandingService = Depends(get_document_understanding_service),
    history: UploadHistoryService = Depends(get_upload_history_service),
) -> PrefillResponse:
    """Apply a document's accepted fields to an interview session."""
    report = pipeline.prefill_session(
        body.document_id, body.session_id, overwrite=body.overwrite
    )
    try:
        history.mark_processed(body.document_id)
    except Exception:  # noqa: BLE001
        logger.warning("Upload history prefill update failed for %s", body.document_id)
    return PrefillResponse.from_domain(report)


@router.get(
    "/{document_id}",
    response_model=OCRExtractResponse,
    summary="Get cached understanding results for a document",
    description=(
        "Returns the cached analysis, OCR statistics, and structured "
        "extraction for a document already processed via POST /ocr or "
        "POST /ocr/extract. Never triggers processing itself."
    ),
    responses={
        404: {"description": "Document not found, or uploaded but never processed."},
    },
)
async def get_understanding(
    document_id: str,
    pipeline: DocumentUnderstandingService = Depends(get_document_understanding_service),
) -> OCRExtractResponse:
    """Return cached pipeline results without re-running anything."""
    record = pipeline.get_processed(document_id)
    return OCRExtractResponse.from_domain(record)
