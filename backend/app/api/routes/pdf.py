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

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.core.dependencies import get_pdf_generation_service
from app.schemas.pdf import (
    DeletePdfResponse,
    GeneratedPdfResponse,
    GeneratePdfRequest,
    GeneratePdfResponse,
)
from app.services.pdf_generation_service import PDFGenerationService

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
) -> GeneratePdfResponse:
    """Generate one filled PDF and return its metadata + download URL."""
    record = pdfs.generate(body.session_id)
    return GeneratePdfResponse(
        message="PDF generated successfully.",
        pdf=GeneratedPdfResponse.from_domain(record),
    )


@router.get(
    "",
    response_model=list[GeneratedPdfResponse],
    summary="List all generated PDFs",
    description="Metadata for every generated PDF, newest first.",
)
async def list_pdfs(
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
) -> list[GeneratedPdfResponse]:
    """Return metadata for all generated PDFs."""
    return [GeneratedPdfResponse.from_domain(r) for r in pdfs.list_records()]


@router.get(
    "/{pdf_id}",
    response_model=GeneratedPdfResponse,
    summary="Get one generated PDF's metadata",
    responses={404: {"description": "Generated PDF not found."}},
)
async def get_pdf(
    pdf_id: str,
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
) -> GeneratedPdfResponse:
    """Return the metadata record for one generated PDF."""
    return GeneratedPdfResponse.from_domain(pdfs.get_record(pdf_id))


@router.get(
    "/{pdf_id}/download",
    summary="Download the generated PDF file",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The PDF file."},
        404: {"description": "Generated PDF not found."},
    },
)
async def download_pdf(
    pdf_id: str,
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
) -> FileResponse:
    """Stream the generated PDF as a file download."""
    path = pdfs.file_path(pdf_id)  # typed 404 if record or file is missing
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"kyc-filled-{pdf_id[:8]}.pdf",
    )


@router.delete(
    "/{pdf_id}",
    response_model=DeletePdfResponse,
    summary="Delete a generated PDF",
    description="Removes both the PDF file and its metadata record.",
    responses={404: {"description": "Generated PDF not found."}},
)
async def delete_pdf(
    pdf_id: str,
    pdfs: PDFGenerationService = Depends(get_pdf_generation_service),
) -> DeletePdfResponse:
    """Delete one generated PDF (file + metadata)."""
    pdfs.delete(pdf_id)
    return DeletePdfResponse(pdf_id=pdf_id, deleted=True)
