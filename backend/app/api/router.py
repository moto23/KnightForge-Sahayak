"""
API router aggregation.

Collects every feature router into a single `api_router` that main.py includes
once. New feature areas (uploads, interview, generate) register here in later
phases — main.py never needs to change per-feature.
"""

from fastapi import APIRouter

from app.api.routes import (
    assets,
    auth,
    chats,
    conversation,
    forms,
    health,
    intelligence,
    knowledge,
    ocr,
    pdf,
    session,
    upload,
    validation,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(forms.router)
api_router.include_router(validation.router)
api_router.include_router(session.router)
api_router.include_router(conversation.router)
api_router.include_router(upload.router)
api_router.include_router(ocr.router)
api_router.include_router(pdf.router)
api_router.include_router(knowledge.router)
api_router.include_router(intelligence.router)
api_router.include_router(assets.router)
api_router.include_router(auth.router)
api_router.include_router(chats.router)
