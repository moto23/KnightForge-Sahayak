"""
Domain exceptions and their HTTP mappings.

Business/domain code raises these plain exceptions and stays completely unaware
of HTTP. `register_exception_handlers()` wires each one to a proper HTTP status
and a consistent JSON error envelope, so every error the API emits looks the
same and routes never hand-build 404s.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base class for all domain-level errors."""

    # Default HTTP status if a subclass doesn't override it.
    status_code: int = 400
    # Stable, machine-readable error code for clients.
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class KYCFieldNotFoundError(DomainError):
    """Raised when a requested KYC field id does not exist in the schema."""

    status_code = 404
    code = "field_not_found"

    def __init__(self, field_id: str) -> None:
        super().__init__(f"KYC field '{field_id}' was not found.")
        self.field_id = field_id


class SessionNotFoundError(DomainError):
    """Raised when a requested interview session id does not exist."""

    status_code = 404
    code = "session_not_found"

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session '{session_id}' was not found.")
        self.session_id = session_id


class InterviewIncompleteError(DomainError):
    """Raised when completing an interview that still has missing required fields."""

    status_code = 409
    code = "interview_incomplete"

    def __init__(self, remaining_field_ids: tuple[str, ...]) -> None:
        super().__init__(
            "Interview cannot be completed — required fields still missing: "
            + ", ".join(remaining_field_ids)
        )
        self.remaining_field_ids = remaining_field_ids


# --------------------------------------------------------------------------- #
# Phase 6 — Document Upload Pipeline
# --------------------------------------------------------------------------- #


class UnsupportedFileTypeError(DomainError):
    """Raised when an upload's extension, MIME type, or content signature is not allowed."""

    status_code = 415
    code = "unsupported_file_type"

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"Unsupported file: {detail} Allowed types: PDF, JPG, JPEG, PNG."
        )


class FileTooLargeError(DomainError):
    """Raised when an upload exceeds the configured maximum size."""

    status_code = 413
    code = "file_too_large"

    def __init__(self, max_mb: int) -> None:
        super().__init__(f"File exceeds the maximum allowed size of {max_mb} MB.")
        self.max_mb = max_mb


class EmptyUploadError(DomainError):
    """Raised when the uploaded file is missing a filename or contains zero bytes."""

    status_code = 400
    code = "empty_file"

    def __init__(self, detail: str = "The uploaded file is empty.") -> None:
        super().__init__(detail)


class FieldNotSkippableError(DomainError):
    """400 - the active form genuinely requires this field, so it cannot be skipped."""

    code = "field_not_skippable"
    status_code = 400

    def __init__(self, display_name: str) -> None:
        super().__init__(
            f"{display_name} is required for this form and cannot be skipped."
        )


class DocumentNotFoundError(DomainError):
    """Raised when a requested document id does not exist."""

    status_code = 404
    code = "document_not_found"

    def __init__(self, document_id: str) -> None:
        super().__init__(f"Document '{document_id}' was not found.")
        self.document_id = document_id


class DuplicateDocumentError(DomainError):
    """Raised when a generated document id collides with an existing record."""

    status_code = 409
    code = "duplicate_document"

    def __init__(self, document_id: str) -> None:
        super().__init__(f"Document '{document_id}' already exists.")
        self.document_id = document_id


# --------------------------------------------------------------------------- #
# Phase 7 — Intelligent Document Understanding Pipeline
# --------------------------------------------------------------------------- #


class OCRFailedError(DomainError):
    """Raised when the OCR engine itself fails or is unavailable (not a bad scan)."""

    status_code = 502
    code = "ocr_failed"

    def __init__(self, detail: str) -> None:
        super().__init__(f"OCR engine failure: {detail}")


class DocumentUnreadableError(DomainError):
    """Raised when a document yields no usable text at all (blank/corrupt pages)."""

    status_code = 422
    code = "document_unreadable"

    def __init__(self, document_id: str, detail: str) -> None:
        super().__init__(
            f"Document '{document_id}' could not be read: {detail}"
        )
        self.document_id = document_id


class DocumentNotProcessedError(DomainError):
    """Raised when results are requested for a document that was never OCR-processed."""

    status_code = 404
    code = "document_not_processed"

    def __init__(self, document_id: str) -> None:
        super().__init__(
            f"Document '{document_id}' has not been processed yet. "
            "Run POST /ocr first."
        )
        self.document_id = document_id


# --------------------------------------------------------------------------- #
# Phase 8 — Smart PDF Generation Engine
# --------------------------------------------------------------------------- #


class PdfTemplateNotFoundError(DomainError):
    """Raised when the KYC template PDF or its coordinate map is missing on disk."""

    status_code = 500
    code = "pdf_template_missing"

    def __init__(self, detail: str) -> None:
        super().__init__(f"PDF template unavailable: {detail}")


class PdfTemplateCorruptError(DomainError):
    """Raised when the template PDF or coordinate map exists but cannot be parsed."""

    status_code = 500
    code = "pdf_template_corrupt"

    def __init__(self, detail: str) -> None:
        super().__init__(f"PDF template is corrupt: {detail}")


class PdfGenerationError(DomainError):
    """Raised when overlay rendering or the final write fails."""

    status_code = 500
    code = "pdf_generation_failed"

    def __init__(self, detail: str) -> None:
        super().__init__(f"PDF generation failed: {detail}")


class GeneratedPdfNotFoundError(DomainError):
    """Raised when a requested generated-PDF id does not exist."""

    status_code = 404
    code = "pdf_not_found"

    def __init__(self, pdf_id: str) -> None:
        super().__init__(f"Generated PDF '{pdf_id}' was not found.")
        self.pdf_id = pdf_id


# --------------------------------------------------------------------------- #
# Phase 10 — Knowledge RAG Engine
# --------------------------------------------------------------------------- #


class KnowledgeUnavailableError(DomainError):
    """Raised when the RAG stack (chromadb / sentence-transformers) is not installed."""

    status_code = 503
    code = "knowledge_unavailable"

    def __init__(self, detail: str) -> None:
        super().__init__(f"Knowledge engine unavailable: {detail}")


class KnowledgeIndexEmptyError(DomainError):
    """Raised when a query arrives before any documents have been indexed."""

    status_code = 409
    code = "knowledge_index_empty"

    def __init__(self) -> None:
        super().__init__(
            "The knowledge index is empty. Run POST /knowledge/index first."
        )


class KnowledgeCorpusMissingError(DomainError):
    """Raised when indexing finds no ingestible documents in the corpus directory."""

    status_code = 404
    code = "knowledge_corpus_missing"

    def __init__(self, directory: str) -> None:
        super().__init__(
            f"No knowledge documents (.md/.txt/.pdf) found in '{directory}'."
        )
        self.directory = directory


# --------------------------------------------------------------------------- #
# Phase 11 — Universal Document Intelligence
# --------------------------------------------------------------------------- #


class DocumentSchemasMissingError(DomainError):
    """Raised when no document-schema JSON files could be loaded from disk."""

    status_code = 500
    code = "document_schemas_missing"

    def __init__(self, directory: str) -> None:
        super().__init__(
            f"No document schemas (*.json) found in '{directory}'. "
            "The Universal Document Intelligence pipeline cannot run without them."
        )
        self.directory = directory


class ConflictNotFoundError(DomainError):
    """Raised when a resolution is requested for a field that has no open conflict."""

    status_code = 404
    code = "conflict_not_found"

    def __init__(self, canonical_id: str) -> None:
        super().__init__(
            f"No conflict exists for canonical field '{canonical_id}'."
        )
        self.canonical_id = canonical_id


class InvalidConflictResolutionError(DomainError):
    """Raised when a conflict resolution names a value/document not among the candidates."""

    status_code = 422
    code = "invalid_conflict_resolution"

    def __init__(self, detail: str) -> None:
        super().__init__(f"Invalid conflict resolution: {detail}")


class InvalidPrimaryFormError(DomainError):
    """Raised when the selected primary form is not an installed KYC form schema."""

    status_code = 422
    code = "invalid_primary_form"

    def __init__(self, form_id: str) -> None:
        super().__init__(
            f"'{form_id}' is not an installed KYC form schema — pick one of the "
            "supported primary forms."
        )
        self.form_id = form_id


class NotAPrimaryFormError(DomainError):
    """
    Raised when a file uploaded into the PRIMARY slot is not a supported KYC
    form (a PAN card, an Aadhaar, a bank statement…).

    The verdict comes from CONTENT classification, never the filename, and it
    is raised BEFORE the document can activate a primary form or merge through
    the primary path — so a misplaced PAN card can never become the target
    document the final PDF is written onto.
    """

    status_code = 422
    code = "not_a_primary_form"

    def __init__(self, detected_label: str) -> None:
        super().__init__(
            "This doesn't appear to be a supported primary KYC form. Please "
            "upload a CVL/CDSL, SBI, HDFC, ICICI or Axis KYC form."
        )
        self.detected_label = detected_label


class PrimaryFormInSupportingSlotError(DomainError):
    """
    Raised when a supported KYC form is uploaded as a SUPPORTING document.

    Not a hard failure of the user's intent — they uploaded a real, supported
    form, just in the wrong slot — so the message points at the fix rather than
    at the mistake.
    """

    status_code = 422
    code = "primary_form_in_supporting_slot"

    def __init__(self, detected_label: str) -> None:
        super().__init__(
            f"This looks like a {detected_label}. Upload it under “Primary "
            "form” — that's the document Sahayak completes for you."
        )
        self.detected_label = detected_label


# --------------------------------------------------------------------------- #
# Phase 15 — Form assets (photograph / signature)
# --------------------------------------------------------------------------- #


class NoActivePrimaryFormError(DomainError):
    """
    Raised when generating a PDF with no primary form active.

    The primary form IS the output document, so without one there is nothing
    to produce — distinct from "the interview is incomplete", which means the
    form exists but is missing answers. Deleting the primary form puts a
    session here, and the message tells the user the one thing that fixes it.
    """

    status_code = 409
    code = "no_active_primary_form"

    def __init__(self) -> None:
        super().__init__(
            "Start a new KYC workflow by uploading a primary KYC form."
        )


class AssetNotRequiredError(DomainError):
    """
    Raised when uploading a photo/signature the ACTIVE form does not ask for.

    Guards the promise that an asset is never collected "just in case": if the
    primary form has no photo box, there is nowhere to put a photograph and the
    upload is refused rather than stored unused.
    """

    status_code = 422
    code = "asset_not_required"

    def __init__(self, kind: str) -> None:
        super().__init__(
            f"Your selected form does not require a {kind} — nothing to upload."
        )
        self.kind = kind


class AssetNotFoundError(DomainError):
    """Raised when a session has no asset of the requested kind."""

    status_code = 404
    code = "asset_not_found"

    def __init__(self, kind: str) -> None:
        super().__init__(f"No {kind} has been uploaded for this session.")
        self.kind = kind


class InvalidAssetError(DomainError):
    """
    Raised when an uploaded photo/signature fails type, size or decode checks.

    Decodability is checked deliberately: a file can carry a valid PNG header
    and still be truncated garbage, and that only surfaces at PDF-generation
    time — long after the user has moved on — unless it is caught here.
    """

    status_code = 422
    code = "invalid_asset"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class AssetTooLargeError(DomainError):
    """Raised when a photo/signature exceeds its per-kind size cap."""

    status_code = 413
    code = "asset_too_large"

    def __init__(self, kind: str, max_mb: float) -> None:
        limit = f"{max_mb:g}"
        super().__init__(f"Your {kind} is too large — the maximum is {limit} MB.")
        self.kind = kind
        self.max_mb = max_mb


# --------------------------------------------------------------------------- #
# Phase 12 — Authentication + Conversation Persistence
# --------------------------------------------------------------------------- #


class EmailAlreadyRegisteredError(DomainError):
    """Raised when registering with an email that already has an account."""

    status_code = 409
    code = "email_registered"

    def __init__(self, email: str) -> None:
        super().__init__(f"An account with '{email}' already exists — sign in instead.")


class InvalidCredentialsError(DomainError):
    """Raised when email/password authentication fails (never says which)."""

    status_code = 401
    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("Incorrect email or password.")


class AuthRequiredError(DomainError):
    """Raised when a protected endpoint is called without a valid access token."""

    status_code = 401
    code = "auth_required"

    def __init__(self, detail: str = "Sign in to use this feature.") -> None:
        super().__init__(detail)


class InvalidRefreshTokenError(DomainError):
    """Raised when the refresh cookie is missing, expired, revoked, or reused."""

    status_code = 401
    code = "invalid_refresh_token"

    def __init__(self, detail: str = "Your session has expired — sign in again.") -> None:
        super().__init__(detail)


class ChatNotFoundError(DomainError):
    """Raised when a chat doesn't exist OR isn't owned by the caller (same 404)."""

    status_code = 404
    code = "chat_not_found"

    def __init__(self, chat_id: str) -> None:
        super().__init__(f"Conversation '{chat_id}' was not found.")
        self.chat_id = chat_id


class OAuthNotConfiguredError(DomainError):
    """Raised when Google sign-in is attempted without configured credentials."""

    status_code = 503
    code = "oauth_not_configured"

    def __init__(self) -> None:
        super().__init__(
            "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET in backend/.env."
        )


class OAuthFailedError(DomainError):
    """Raised when the Google OAuth exchange fails (bad code, network, etc.)."""

    status_code = 502
    code = "oauth_failed"

    def __init__(self, detail: str) -> None:
        super().__init__(f"Google sign-in failed: {detail}")


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers that turn DomainErrors into consistent JSON responses."""

    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        # Log at warning level — these are expected, client-driven errors.
        logger.warning("Domain error (%s): %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
