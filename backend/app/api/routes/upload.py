"""
Document upload endpoints — the Phase 6 upload pipeline over HTTP.

Thin layer over UploadService: routes translate multipart requests and DTOs
and delegate. All policy (allowed types, size cap, naming, storage layout)
lives in the service; all failures surface as typed DomainErrors through the
global handlers (400 empty_file, 413 file_too_large, 415 unsupported_file_type,
404 document_not_found, 409 duplicate_document).
"""

import logging

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.core.rate_limit import upload_limiter, limit
from app.core.dependencies import (
    owned_document,
    get_current_user,
    get_document_intelligence_service,
    get_document_understanding_service,
    get_optional_user,
    get_session_service,
    get_upload_history_service,
    get_upload_service,
)
from app.services.document_intelligence_service import DocumentIntelligenceService
from app.services.session_service import SessionService
from app.infrastructure.db.models import User
from app.schemas.upload import (
    DeleteUploadResponse,
    DocumentMetadataResponse,
    ListUploadsResponse,
    UploadHistoryItemResponse,
    UploadHistoryResponse,
    UploadResponse,
)
from app.services.document_understanding_service import DocumentUnderstandingService
from app.services.upload_history_service import UploadHistoryService
from app.services.upload_service import UploadService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["Document Upload"])


@router.post(
    "",
    dependencies=[Depends(limit(upload_limiter))],
    response_model=UploadResponse,
    status_code=201,
    summary="Upload a document",
    description=(
        "Accepts one PDF, JPG, JPEG, or PNG up to 10 MB via multipart/form-data "
        "(field name: `file`). The file is validated by extension, MIME type, "
        "size, and content signature, then stored under a server-generated UUID."
    ),
    responses={
        400: {"description": "Empty file or missing filename."},
        413: {"description": "File exceeds the 10 MB limit."},
        415: {"description": "Extension, MIME type, or content is not an allowed type."},
        422: {"description": "The `file` form field is missing entirely."},
    },
)
async def upload_document(
    file: UploadFile = File(..., description="The PDF or image to upload."),
    document_type: str = Form(
        "other",
        description=(
            "User-selected document type: kyc_form, pan_card, aadhaar_card, "
            "passport, driving_licence, bank_statement, utility_bill, other."
        ),
    ),
    uploads: UploadService = Depends(get_upload_service),
    history: UploadHistoryService = Depends(get_upload_history_service),
    user: User | None = Depends(get_optional_user),
) -> UploadResponse:
    """Validate and store one uploaded document; return its metadata."""
    document = await uploads.store_upload(file, owner_id=user.id if user else None)
    try:
        # Best-effort journal (Phase 13) — history must never fail an upload.
        history.record_upload(
            document_id=document.document_id,
            filename=document.original_filename,
            document_type=document_type,
            file_size=document.file_size,
            user_id=user.id if user else None,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Upload history write failed for %s", document.document_id)
    return UploadResponse(
        message="File uploaded successfully.",
        document=DocumentMetadataResponse.from_document(document),
    )


@router.get(
    "/history",
    response_model=UploadHistoryResponse,
    summary="Your persistent upload history",
    description=(
        "Every document the signed-in account has uploaded, newest first — "
        "filename, selected/detected type, OCR status, processing status. "
        "Survives restarts (SQLite). Guests have no history (sign in to keep one)."
    ),
    responses={401: {"description": "Sign in to see your upload history."}},
)
async def upload_history(
    user: User = Depends(get_current_user),
    history: UploadHistoryService = Depends(get_upload_history_service),
) -> UploadHistoryResponse:
    """Return the caller's upload-history rows, newest first."""
    rows = history.list_for_user(user.id)
    return UploadHistoryResponse(
        total=len(rows),
        items=[UploadHistoryItemResponse.from_row(row) for row in rows],
    )


@router.get(
    "",
    response_model=ListUploadsResponse,
    summary="List uploaded documents",
    description="Metadata for every stored document, newest upload first.",
)
async def list_documents(
    session_id: str | None = None,
    uploads: UploadService = Depends(get_upload_service),
    intelligence: DocumentIntelligenceService = Depends(
        get_document_intelligence_service
    ),
    sessions: SessionService = Depends(get_session_service),
    user: User | None = Depends(get_optional_user),
) -> ListUploadsResponse:
    """
    Return the CALLER's stored uploads, optionally narrowed to one session.

    This used to return every document held by the process, to anyone. That
    was both a metadata leak and the cause of a phantom third file: the Upload
    page hydrates "documents in this session" from here, so a bank statement
    left over from an earlier session reappeared beside a fresh PAN + Aadhaar
    upload and looked as though it had been uploaded again.

    `session_id` narrows the list to the documents that session actually
    processed — the authoritative per-session set, which lives in the profile
    state — so the page shows this workflow's evidence and nothing else.
    """
    user_id = user.id if user else None
    documents = [
        doc
        for doc in uploads.list_documents()
        if getattr(doc, "owner_id", None) is None
        or getattr(doc, "owner_id", None) == user_id
    ]
    if session_id:
        sessions.assert_owner(session_id, user_id)  # typed 404 when not theirs
        known = set(intelligence.get_profile(session_id).state.documents)
        documents = [doc for doc in documents if doc.document_id in known]
    return ListUploadsResponse(
        total=len(documents),
        documents=[DocumentMetadataResponse.from_document(doc) for doc in documents],
    )


@router.get(
    "/{document_id}",
    response_model=DocumentMetadataResponse,
    summary="Get one document's metadata",
    responses={404: {"description": "Document not found."}},
)
async def get_document(
    document_id: str = Depends(owned_document),
    uploads: UploadService = Depends(get_upload_service),
) -> DocumentMetadataResponse:
    """Return the metadata record for one uploaded document."""
    return DocumentMetadataResponse.from_document(uploads.get_document(document_id))


@router.get(
    "/{document_id}/file",
    summary="View the original uploaded file",
    description=(
        "Streams the stored bytes back with the document's canonical content "
        "type (inline disposition), so the frontend can preview exactly what "
        "was uploaded — persisting across OCR, refresh, and navigation."
    ),
    responses={404: {"description": "Document not found."}},
    response_class=Response,
)
async def get_document_file(
    document_id: str = Depends(owned_document),
    uploads: UploadService = Depends(get_upload_service),
) -> Response:
    """Return the raw stored bytes for in-browser document preview."""
    document = uploads.get_document(document_id)
    content = uploads.read_content(document)
    return Response(
        content=content,
        media_type=document.content_type,
        headers={
            # stored_filename is <uuid><ext> — always header-safe ASCII.
            "Content-Disposition": f'inline; filename="{document.stored_filename}"',
        },
    )


@router.delete(
    "/{document_id}",
    response_model=DeleteUploadResponse,
    summary="Delete a document",
    description="Removes both the stored file and its metadata record.",
    responses={404: {"description": "Document not found."}},
)
async def delete_document(
    document_id: str = Depends(owned_document),
    uploads: UploadService = Depends(get_upload_service),
    understanding: DocumentUnderstandingService = Depends(
        get_document_understanding_service
    ),
    history: UploadHistoryService = Depends(get_upload_history_service),
) -> DeleteUploadResponse:
    """Delete one uploaded document (bytes + metadata + cached OCR results)."""
    uploads.delete_document(document_id)
    understanding.forget(document_id)  # drop any cached Phase 7 pipeline result
    try:
        history.mark_deleted(document_id)  # keep the audit row, flip its status
    except Exception:  # noqa: BLE001
        logger.warning("Upload history update failed for %s", document_id)
    return DeleteUploadResponse(document_id=document_id, deleted=True)
