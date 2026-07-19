"""
Form asset endpoints — the photograph and signature a KYC form may require.

    GET    /assets/{session_id}                — what this form needs + what's supplied
    POST   /assets/{session_id}/{kind}         — upload a photo or signature
    GET    /assets/{session_id}/{kind}/file    — preview the stored image
    DELETE /assets/{session_id}/{kind}         — remove it (field returns to PENDING)

Thin over AssetService: all policy (accepted types, per-kind size caps,
decodability, "is this even required?") lives in the service, and every
failure surfaces as a typed DomainError through the global handlers.

Guest-accessible by construction, like every other session endpoint — an asset
belongs to a session, not to an account.
"""

import logging

from fastapi import APIRouter, Depends, File, Path, Response, UploadFile

from app.core.dependencies import (
    owned_session,
    get_asset_service,
    get_document_intelligence_service,
)
from app.domain.form_assets import AssetKind
from app.schemas.assets import (
    AssetDeleteResponse,
    AssetUploadResponse,
    SessionAssetResponse,
    SessionAssetsResponse,
)
from app.services.asset_service import AssetService
from app.services.document_intelligence_service import DocumentIntelligenceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["Form Assets"])


@router.get(
    "/{session_id}",
    response_model=SessionAssetsResponse,
    summary="What photo/signature this session's form requires",
    description=(
        "Returns one entry per asset kind with `required` (does the ACTIVE "
        "primary form ask for it?) and `provided` (has the user supplied it?). "
        "A form with no photo box reports required=false, and the interview "
        "never raises the question."
    ),
    responses={404: {"description": "Session not found."}},
)
async def get_session_assets(
    session_id: str = Depends(owned_session),
    assets: AssetService = Depends(get_asset_service),
    intelligence: DocumentIntelligenceService = Depends(
        get_document_intelligence_service
    ),
) -> SessionAssetsResponse:
    """Report asset requirements and current state for one session."""
    # Re-sync first so a primary form deleted since the last call has already
    # retired its requirements — otherwise this would report a stale "photo
    # required" for a form that no longer exists.
    intelligence.get_profile(session_id)
    stored = {asset.kind: asset for asset in assets.list_for_session(session_id)}
    return SessionAssetsResponse.build(
        session_id, intelligence.asset_requirements(session_id), stored
    )


@router.post(
    "/{session_id}/{kind}",
    response_model=AssetUploadResponse,
    status_code=201,
    summary="Upload a photograph or signature",
    description=(
        "Accepts one JPG/JPEG/PNG via multipart/form-data (field name: `file`). "
        "Photographs are capped at 5 MB, signatures at 2 MB. The image is "
        "validated by declared type, size, magic bytes AND actual decodability, "
        "then stored and recorded as the answer to its interview field — so "
        "progress, the next question and the PDF gate all update at once. "
        "Uploading again replaces the previous image."
    ),
    responses={
        404: {"description": "Session not found."},
        413: {"description": "The image exceeds this kind's size cap."},
        422: {
            "description": (
                "Not a readable JPG/PNG, or the active form does not require "
                "this asset."
            )
        },
    },
)
async def upload_asset(
    session_id: str = Depends(owned_session),
    kind: AssetKind = Path(..., description="photo | signature."),
    file: UploadFile = File(..., description="The JPG or PNG image."),
    assets: AssetService = Depends(get_asset_service),
) -> AssetUploadResponse:
    """Validate and store one photograph/signature for a session."""
    content = await file.read()
    asset = assets.store(
        session_id=session_id,
        kind=kind,
        filename=file.filename or "",
        declared_mime=file.content_type,
        content=content,
    )
    return AssetUploadResponse(
        message=f"Your {kind.value} was saved.",
        asset=SessionAssetResponse.from_asset(asset),
    )


@router.get(
    "/{session_id}/{kind}/file",
    summary="Preview a stored photograph or signature",
    description="Streams the stored image back inline for in-browser preview.",
    responses={404: {"description": "Session has no asset of this kind."}},
    response_class=Response,
)
async def get_asset_file(
    session_id: str = Depends(owned_session),
    kind: AssetKind = Path(..., description="photo | signature."),
    assets: AssetService = Depends(get_asset_service),
) -> Response:
    """Return the raw stored image bytes."""
    from app.core.exceptions import AssetNotFoundError

    asset = assets.get(session_id, kind)
    if asset is None:
        raise AssetNotFoundError(kind.value)
    return Response(
        content=assets.read_bytes(asset),
        media_type=asset.content_type,
        headers={
            # stored_filename is 'asset-<uuid><ext>' — always header-safe ASCII.
            "Content-Disposition": f'inline; filename="{asset.stored_filename}"',
        },
    )


@router.delete(
    "/{session_id}/{kind}",
    response_model=AssetDeleteResponse,
    summary="Remove a photograph or signature",
    description=(
        "Deletes the stored image and returns its interview field to PENDING, "
        "so progress drops and the interview asks for it again."
    ),
    responses={404: {"description": "Session has no asset of this kind."}},
)
async def delete_asset(
    session_id: str = Depends(owned_session),
    kind: AssetKind = Path(..., description="photo | signature."),
    assets: AssetService = Depends(get_asset_service),
) -> AssetDeleteResponse:
    """Delete one asset and recompute the session."""
    assets.delete(session_id, kind)
    return AssetDeleteResponse(kind=kind)
