"""
Health check endpoint.

Used by developers, load balancers, and uptime monitors to confirm the API
process is alive. Deliberately dependency-free (no DB, no external services)
so it answers instantly and never false-alarms.
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Response schema — shows up in Swagger with an example."""

    status: str = "ok"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns `{\"status\": \"ok\"}` when the API is up.",
)
async def health() -> HealthResponse:
    """Liveness probe: if this responds, the server process is healthy."""
    logger.debug("Health check hit")
    return HealthResponse(status="ok")
