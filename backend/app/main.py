"""
Application entrypoint.

Builds the FastAPI app via an app-factory (`create_app`) so tests can create
isolated instances later, and exposes a module-level `app` so it starts with:

    uvicorn app.main:app --reload

Responsibilities here (and ONLY here):
  * initialize logging
  * create the FastAPI instance with Swagger/OpenAPI metadata
  * register middleware (CORS)
  * register routers (health today; upload/interview/etc. in later phases)
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """App factory: build and return a fully configured FastAPI instance."""
    setup_logging()

    application = FastAPI(
        title=settings.APP_NAME,
        description=settings.APP_DESCRIPTION,
        version=settings.APP_VERSION,
        # Swagger UI and OpenAPI schema locations (FastAPI defaults, explicit
        # here so they're documented in one place).
        docs_url="/docs",       # interactive Swagger UI
        redoc_url="/redoc",     # alternative ReDoc UI
        openapi_url="/openapi.json",
    )

    # --- CORS ---
    # Allows the (future) frontend dev servers to call this API from a browser.
    # Origins come from settings so production can lock this down via .env.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Routers ---
    # All feature routers are aggregated in api/router.py; main.py includes the
    # aggregate once and never changes per-feature.
    application.include_router(api_router)

    # --- Error handling ---
    # Maps typed DomainErrors to consistent JSON error responses.
    register_exception_handlers(application)

    logger.info(
        "%s v%s started (env=%s, debug=%s)",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
        settings.DEBUG,
    )
    return application


# Module-level ASGI app — the target of `uvicorn app.main:app --reload`.
app = create_app()
