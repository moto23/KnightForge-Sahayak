"""Pydantic DTOs for the /assets endpoints (photograph + signature)."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.form_assets import (
    ASSET_FIELD_IDS,
    ASSET_MAX_BYTES,
    AssetKind,
    FormAssetRequirements,
    SessionAsset,
)


class SessionAssetResponse(BaseModel):
    """One stored photograph/signature."""

    asset_id: str = Field(..., description="Unique asset id (also the field's answer).")
    kind: AssetKind = Field(..., description="photo | signature.")
    field_id: str = Field(..., description="Interview field this asset answers.")
    original_filename: str = Field(..., description="Name the user uploaded it under.")
    content_type: str = Field(..., description="image/jpeg or image/png.")
    file_size: int = Field(..., description="Size in bytes.")
    width: int = Field(..., description="Decoded pixel width.")
    height: int = Field(..., description="Decoded pixel height.")
    uploaded_at: datetime = Field(..., description="When it was uploaded (UTC).")
    file_url: str = Field(..., description="Where the image can be previewed.")

    @classmethod
    def from_asset(cls, asset: SessionAsset) -> "SessionAssetResponse":
        return cls(
            asset_id=asset.asset_id,
            kind=asset.kind,
            field_id=ASSET_FIELD_IDS[asset.kind],
            original_filename=asset.original_filename,
            content_type=asset.content_type,
            file_size=asset.file_size,
            width=asset.width,
            height=asset.height,
            uploaded_at=asset.uploaded_at,
            file_url=f"/assets/{asset.session_id}/{asset.kind.value}/file",
        )


class AssetRequirementResponse(BaseModel):
    """
    One asset kind's status for a session — the shape the interview and
    Progress both render from, so "Pending"/"Complete" is decided in exactly
    one place rather than recomputed differently on two screens.
    """

    kind: AssetKind = Field(..., description="photo | signature.")
    field_id: str = Field(..., description="Interview field id for this asset.")
    required: bool = Field(..., description="Does the ACTIVE form ask for it?")
    provided: bool = Field(..., description="Has the user supplied it?")
    max_bytes: int = Field(..., description="Per-kind upload cap in bytes.")
    accepted_types: tuple[str, ...] = Field(
        default=("image/jpeg", "image/png"), description="Accepted MIME types."
    )
    asset: SessionAssetResponse | None = Field(
        default=None, description="The stored asset, when one exists."
    )


class SessionAssetsResponse(BaseModel):
    """Everything a client needs to render the asset step of a session."""

    session_id: str = Field(..., description="The session these assets belong to.")
    detected_from: str = Field(
        ...,
        description=(
            "'document' when the uploaded form itself was inspected, 'schema' "
            "when only its JSON declaration was available, 'none' when no "
            "primary form is active."
        ),
    )
    requirements: tuple[AssetRequirementResponse, ...] = Field(
        ..., description="One entry per asset kind, always both."
    )

    @classmethod
    def build(
        cls,
        session_id: str,
        requirements: FormAssetRequirements | None,
        assets: dict[AssetKind, SessionAsset],
    ) -> "SessionAssetsResponse":
        return cls(
            session_id=session_id,
            detected_from=requirements.detected_from if requirements else "none",
            requirements=tuple(
                AssetRequirementResponse(
                    kind=kind,
                    field_id=ASSET_FIELD_IDS[kind],
                    required=bool(requirements and requirements.requires(kind)),
                    provided=kind in assets,
                    max_bytes=ASSET_MAX_BYTES[kind],
                    asset=(
                        SessionAssetResponse.from_asset(assets[kind])
                        if kind in assets
                        else None
                    ),
                )
                for kind in AssetKind
            ),
        )


class AssetUploadResponse(BaseModel):
    """Result of storing one asset."""

    message: str = Field(..., description="Human-readable confirmation.")
    asset: SessionAssetResponse = Field(..., description="The stored asset.")


class AssetDeleteResponse(BaseModel):
    """Result of removing one asset."""

    kind: AssetKind = Field(..., description="Which asset was removed.")
    deleted: bool = Field(default=True, description="Always true on success.")
