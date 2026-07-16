"""
Document upload endpoints — the Phase 6 upload pipeline over HTTP.

Thin layer over UploadService: routes translate multipart requests and DTOs
and delegate. All policy (allowed types, size cap, naming, storage layout)
lives in the service; all failures surface as typed DomainErrors through the
global handlers (400 empty_file, 413 file_too_large, 415 unsupported_file_type,
404 document_not_found, 409 duplicate_document).
"""

import logging

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.dependencies import get_document_understanding_service, get_upload_service
from app.schemas.upload import (
    DeleteUploadResponse,
    DocumentMetadataResponse,
    ListUploadsResponse,
    UploadResponse,
)
from app.services.document_understanding_service import DocumentUnderstandingService
from app.services.upload_service import UploadService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["Document Upload"])


@router.post(
    "",
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
    uploads: UploadService = Depends(get_upload_service),
) -> UploadResponse:
    """Validate and store one uploaded document; return its metadata."""
    document = await uploads.store_upload(file)
    return UploadResponse(
        message="File uploaded successfully.",
        document=DocumentMetadataResponse.from_document(document),
    )


@router.get(
    "",
    response_model=ListUploadsResponse,
    summary="List uploaded documents",
    description="Metadata for every stored document, newest upload first.",
)
async def list_documents(
    uploads: UploadService = Depends(get_upload_service),
) -> ListUploadsResponse:
    """Return metadata for all stored uploads."""
    documents = uploads.list_documents()
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
    document_id: str,
    uploads: UploadService = Depends(get_upload_service),
) -> DocumentMetadataResponse:
    """Return the metadata record for one uploaded document."""
    return DocumentMetadataResponse.from_document(uploads.get_document(document_id))


@router.delete(
    "/{document_id}",
    response_model=DeleteUploadResponse,
    summary="Delete a document",
    description="Removes both the stored file and its metadata record.",
    responses={404: {"description": "Document not found."}},
)
async def delete_document(
    document_id: str,
    uploads: UploadService = Depends(get_upload_service),
    understanding: DocumentUnderstandingService = Depends(
        get_document_understanding_service
    ),
) -> DeleteUploadResponse:
    """Delete one uploaded document (bytes + metadata + cached OCR results)."""
    uploads.delete_document(document_id)
    understanding.forget(document_id)  # drop any cached Phase 7 pipeline result
    return DeleteUploadResponse(document_id=document_id, deleted=True)
