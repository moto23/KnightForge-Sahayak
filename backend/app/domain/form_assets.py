"""
Form asset domain models — the photograph and signature a KYC form may require.

Some KYC forms print a photo box ("Affix recent passport-size photograph") and
a signature line ("Signature of Applicant"); many do not. Whether a session
must collect them is therefore a property of the ACTIVE primary form, never a
product-wide assumption — exactly like `required_canonical`.

Two ideas live here:

    FormAssetRequirements — does THIS form need a photo/signature, and where
                            on the page does each belong?
    SessionAsset          — one image the user actually supplied.

Both are pure data. Detection (which reads a PDF) is a service; storage is a
port. Nothing in this module does I/O or imports a framework.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.session import utc_now


class AssetKind(str, Enum):
    """The two image assets a KYC form can ask an applicant to supply."""

    PHOTO = "photo"
    SIGNATURE = "signature"


# The interview field each asset kind answers. Declared here (not in the
# services) so the interview, progress, PDF gate and asset upload all agree on
# one id per kind and can never drift apart.
ASSET_FIELD_IDS: dict[AssetKind, str] = {
    AssetKind.PHOTO: "applicant_photo",
    AssetKind.SIGNATURE: "applicant_signature",
}

FIELD_ID_TO_ASSET: dict[str, AssetKind] = {v: k for k, v in ASSET_FIELD_IDS.items()}

# Per-kind upload policy. A photograph is a real photo (5 MB); a signature is a
# small crop or scan of a signed line (2 MB). PDFs are deliberately NOT allowed
# for either — these are placed as images inside a box on the page.
ASSET_MAX_BYTES: dict[AssetKind, int] = {
    AssetKind.PHOTO: 5 * 1024 * 1024,
    AssetKind.SIGNATURE: 2 * 1024 * 1024,
}

ASSET_ALLOWED_MIME: frozenset[str] = frozenset(
    {"image/jpeg", "image/jpg", "image/png"}
)


class AssetRegion(BaseModel):
    """
    Where one asset belongs on one page of the uploaded form.

    Coordinates are in PDF points, top-left origin, exactly as PyMuPDF reports
    them — DISCOVERED per document rather than read from a hand-measured table,
    so an unseen form still places correctly.
    """

    model_config = ConfigDict(frozen=True)

    page: int = Field(..., ge=0, description="0-based page index the region is on.")
    x0: float = Field(..., description="Left edge in PDF points.")
    y0: float = Field(..., description="Top edge in PDF points.")
    x1: float = Field(..., description="Right edge in PDF points.")
    y1: float = Field(..., description="Bottom edge in PDF points.")
    source: str = Field(
        ...,
        description="How the region was found: 'acroform' | 'layout' — reported "
        "so a low-confidence layout guess can be told from a real widget.",
    )
    matched_text: str = Field(
        default="",
        description="The widget name or printed caption that produced this region.",
    )
    score: int = Field(
        default=0,
        description=(
            "How strongly the caption identifies this asset. Higher wins when a "
            "form prints several signature-ish phrases: 'Signature of Applicant' "
            "outranks a bare 'Signature', which outranks a 'sign across' hint."
        ),
    )

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class FormAssetRequirements(BaseModel):
    """
    What the active primary form demands, plus where to put it.

    `photo`/`signature` being False is a POSITIVE finding, not an absence of
    information: the form was inspected and asks for neither, so the interview
    must never raise the question.
    """

    model_config = ConfigDict(frozen=True)

    photo: bool = Field(default=False, description="Form requires a photograph.")
    signature: bool = Field(default=False, description="Form requires a signature.")
    photo_regions: tuple[AssetRegion, ...] = Field(
        default=(), description="Candidate photo boxes, best first."
    )
    signature_regions: tuple[AssetRegion, ...] = Field(
        default=(), description="Candidate signature areas, best first."
    )
    detected_from: str = Field(
        default="schema",
        description=(
            "'document' when the uploaded PDF itself was inspected, 'schema' "
            "when only the form's JSON declaration was available."
        ),
    )

    def requires(self, kind: AssetKind) -> bool:
        return self.photo if kind is AssetKind.PHOTO else self.signature

    def regions(self, kind: AssetKind) -> tuple[AssetRegion, ...]:
        return self.photo_regions if kind is AssetKind.PHOTO else self.signature_regions

    @property
    def required_field_ids(self) -> tuple[str, ...]:
        """Interview field ids this form's asset requirements add."""
        return tuple(
            ASSET_FIELD_IDS[kind] for kind in AssetKind if self.requires(kind)
        )


class SessionAsset(BaseModel):
    """One photo/signature image a session actually holds."""

    model_config = ConfigDict(frozen=True)

    asset_id: str = Field(..., description="Unique id (also the session answer value).")
    session_id: str = Field(..., description="Session this asset belongs to.")
    kind: AssetKind = Field(..., description="photo | signature.")
    original_filename: str = Field(..., description="Display name only.")
    stored_filename: str = Field(..., description="<uuid><ext> on disk — never user input.")
    content_type: str = Field(..., description="Canonical image MIME type.")
    file_size: int = Field(..., ge=1, description="Size in bytes.")
    width: int = Field(..., ge=1, description="Decoded pixel width.")
    height: int = Field(..., ge=1, description="Decoded pixel height.")
    uploaded_at: datetime = Field(default_factory=utc_now, description="Upload time (UTC).")
