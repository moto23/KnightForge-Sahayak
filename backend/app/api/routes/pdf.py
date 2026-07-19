"""
PDF generation endpoints (Phase 8) — the /pdf surface.

Thin layer over PDFGenerationService, zero business logic in routes:

    POST   /pdf/generate           — fill the KYC form from a COMPLETED session
    GET    /pdf                    — list all generated PDFs
    GET    /pdf/{pdf_id}           — metadata for one generated PDF
    GET    /pdf/{pdf_id}/download  — stream the actual PDF file
    DELETE /pdf/{pdf_id}           — remove file + metadata

Failures surface as typed DomainErrors through the global handlers:
404 session_not_found / pdf_not_found, 409 interview_incomplete (with the
missing field ids in the message), 500 pdf_template_missing /
pdf_template_corrupt / pdf_generation_failed.
"""

import logging

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse

from app.core.dependencies import (
    get_optional_user,
    get_pdf_generation_service,
    get_session_service,
    owned_pdf,
)
from app.core.exceptions import DomainError
from app.domain.pdf import fingerprint_answers
from app.infrastructure.db.models import User
from app.schemas.pdf import (
    DeletePdfResponse,
    GeneratedPdfResponse,
    GeneratePdfRequest,
    GeneratePdfResponse,
)
from app.services.pdf_generation_service import PDFGenerationService
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pdf", tags=["PDF Generation"])


@router.post(
    "/generate",
    response_model=GeneratePdfResponse,
    status_code=201,
    summary="Generate the filled KYC PDF from a completed session",
    description=(
        "Fills the original CVL KYC template with the session's VALIDATED "
        "answers (Session.answers — the single source of truth; OCR results "
        "are never used directly). The interview must be complete: if any "
        "required field is unanswered, a 409 lists exactly which ones."
    ),
    responses={
        404: {"description": "Session not found."},
        409: {"description": "Interview incomplete — missing required fields listed."},
        500: {"description": "Template missing/corrupt or generation failed."},
    },
)
async def generate_pdf(
    body: GeneratePdfRequest,
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
    sessions: SessionService = Depends(get_session_service),
    user: User | None = Depends(get_optional_user),
) -> GeneratePdfResponse:
    """Generate one filled PDF and return its metadata + download URL."""
    # The session named in the body decides entitlement: generating a PDF
    # renders somebody's PAN, Aadhaar, photograph and signature onto a page.
    sessions.assert_owner(body.session_id, user.id if user else None)
    record = pdfs.generate(body.session_id)
    return GeneratePdfResponse(
        message="PDF generated successfully.",
        pdf=GeneratedPdfResponse.from_domain(record),
    )


@router.get(
    "",
    response_model=list[GeneratedPdfResponse],
    summary="List all generated PDFs",
    description=(
        "Metadata for every generated PDF, newest first — the immutable "
        "history. Pass `session_id` to have each record report whether it "
        "still matches that session's CURRENT answers (`is_current`); records "
        "themselves are never rewritten."
    ),
)
async def list_pdfs(
    session_id: str | None = None,
    user: User | None = Depends(get_optional_user),
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
    sessions: SessionService = Depends(get_session_service),
) -> list[GeneratedPdfResponse]:
    """Return metadata for all generated PDFs, flagging the current one."""
    fingerprint: str | None = None
    if session_id:
        try:
            fingerprint = fingerprint_answers(sessions.get_session(session_id).answers)
        except DomainError:
            fingerprint = None  # unknown session: everything is simply history
    # History is per-user: without this filter the list handed every caller
    # the metadata of every PDF the deployment had ever produced.
    user_id = user.id if user else None
    return [
        GeneratedPdfResponse.from_domain(r, fingerprint)
        for r in pdfs.list_records()
        if sessions.may_access(r.generated_by_session, user_id)
    ]


@router.get(
    "/{pdf_id}",
    response_model=GeneratedPdfResponse,
    summary="Get one generated PDF's metadata",
    responses={404: {"description": "Generated PDF not found."}},
)
async def get_pdf(
    pdf_id: str = Depends(owned_pdf),
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
) -> GeneratedPdfResponse:
    """Return the metadata record for one generated PDF."""
    return GeneratedPdfResponse.from_domain(pdfs.get_record(pdf_id))


@router.get(
    "/{pdf_id}/download",
    summary="Download the generated PDF file",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The PDF file."},
        404: {"description": "Generated PDF not found."},
    },
)
async def download_pdf(
    pdf_id: str = Depends(owned_pdf),
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
) -> Response:
    """
    Stream the generated PDF as a file download.

    Reads BYTES rather than a path: in production the file lives in a private
    object store with no filesystem path. Ownership is still enforced by
    `owned_pdf` before anything is read, and the bytes are served through this
    endpoint rather than a public object URL, so the bucket stays private.
    """
    content = pdfs.read_bytes(pdf_id)  # typed 404 if record or object is missing
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="kyc-filled-{pdf_id[:8]}.pdf"'
            )
        },
    )


@router.delete(
    "/{pdf_id}",
    response_model=DeletePdfResponse,
    summary="Delete a generated PDF",
    description="Removes both the PDF file and its metadata record.",
    responses={404: {"description": "Generated PDF not found."}},
)
async def delete_pdf(
    pdf_id: str = Depends(owned_pdf),
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
) -> DeletePdfResponse:
    """Delete one generated PDF (file + metadata)."""
    pdfs.delete(pdf_id)
    return DeletePdfResponse(pdf_id=pdf_id, deleted=True)
