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
