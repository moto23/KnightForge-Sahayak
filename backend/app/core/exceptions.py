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
