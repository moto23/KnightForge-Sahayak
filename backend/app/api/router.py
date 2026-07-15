"""
API router aggregation.

Collects every feature router into a single `api_router` that main.py includes
once. New feature areas (uploads, interview, generate) register here in later
phases — main.py never needs to change per-feature.
"""

from fastapi import APIRouter

from app.api.routes import conversation, forms, health, session, upload, validation

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(forms.router)
api_router.include_router(validation.router)
api_router.include_router(session.router)
api_router.include_router(conversation.router)
api_router.include_router(upload.router)
