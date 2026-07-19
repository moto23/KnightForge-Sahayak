"""
FormAssetDetector — does the uploaded primary form ask for a photo/signature?

Detection priority (deliberately cheapest-and-surest first):

  1. ACROFORM METADATA — the PDF carries a real widget whose name says
     "photo"/"signature". The form's own author told us; nothing beats that,
     and the widget rectangle IS the placement region.

  2. PRINTED-LABEL LAYOUT — a flat/scanned form. Every word's bounding box is
     read from the page and matched against the caption aliases below. The
     region is inferred from the caption's own geometry.

  3. SCHEMA DECLARATION — no PDF to inspect (the user only *selected* a form).
     Falls back to what the form's JSON declares.

No AI is used, and no image is ever sent anywhere: this is pure geometry over
the document the user already gave us. That matters — a photograph and a
signature are the two most sensitive things on a KYC form.

The hard part is telling the two apart. KYC forms print several signature-ish
phrases, and most of them are NOT where the signature goes:

    "Signature of Applicant"   -> yes, the real signature line   (score 5)
    "Signature"                -> probably                       (score 3)
    "Sign across the photograph" -> a PHOTO instruction, not a
                                    signature field              (rejected)

So captions are SCORED rather than matched, and the photo-adjacent ones are
excluded outright. Blindly writing the signature into every region containing
"sign" would stamp it across the applicant's face.
"""

import logging
import re

import fitz  # PyMuPDF

from app.domain.form_assets import AssetRegion, FormAssetRequirements

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Caption vocabulary. Ordered by specificity: the longest/most explicit phrase
# that matches decides the score, so a form printing BOTH "Signature" and
# "Signature of Applicant" resolves to the latter.
# --------------------------------------------------------------------------- #

_PHOTO_CAPTIONS: tuple[tuple[str, int], ...] = (
    ("passport size photograph", 5),
    ("passport sized photograph", 5),
    ("recent passport size photo", 5),
    ("affix recent photograph", 5),
    ("affix photograph", 5),
    ("affix photo", 5),
    ("paste photograph", 5),
    ("recent photograph", 4),
    ("applicant photo", 4),
    ("applicant photograph", 4),
    ("photograph", 3),
    ("photo", 2),
)

_SIGNATURE_CAPTIONS: tuple[tuple[str, int], ...] = (
    ("signature of applicant", 5),
    ("signature of the applicant", 5),
    ("applicant signature", 5),
    ("signature of account holder", 5),
    ("signature of the holder", 5),
    ("holder signature", 4),
    ("specimen signature", 4),
    ("sign here", 4),
    ("signature", 3),
)

# Phrases that contain a signature word but mark the PHOTO, not a signature
# field. "Sign across the photograph" is an instruction to sign over the photo;
# treating it as a signature region puts the signature on the applicant's face.
_PHOTO_ADJACENT_SIGNATURE = re.compile(
    r"sign\s*(ature)?\s*across|across\s+the\s+photo|sign\s+on\s+the\s+photo",
    re.I,
)

# Printed guidance rather than a field ("please sign in the box overleaf").
_INSTRUCTION = re.compile(
    r"please\s+(refer|read|note)|as\s+per\s+guideline|overleaf|instructions?\s+for",
    re.I,
)

# A photo box on a KYC form is roughly passport-sized and never page-wide.
_MIN_PHOTO_SIDE = 30.0
_MAX_PHOTO_SIDE = 260.0

# A field caption is short ("Signature of Applicant", "Affix recent
# photograph"). Anything longer is prose — the numbered guidance paragraphs on
# a KYC form's back page mention "photograph" repeatedly without marking a
# photo box anywhere. Without this guard those paragraphs become candidate
# regions and an unlucky ranking would paste the applicant's photo onto the
# instructions page.
_MAX_CAPTION_WORDS = 14


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — caption comparison."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _score_caption(text: str, vocabulary: tuple[tuple[str, int], ...]) -> int:
    """Best score any caption in `vocabulary` earns against `text` (0 = none)."""
    normalized = _normalize(text)
    if not normalized:
        return 0
    best = 0
    for phrase, score in vocabulary:
        if phrase in normalized and score > best:
            best = score
    return best


class FormAssetDetector:
    """Inspect a form PDF for photo/signature requirements and their regions."""

    def detect(
        self,
        pdf_bytes: bytes | None,
        schema_photo: bool = False,
        schema_signature: bool = False,
    ) -> FormAssetRequirements:
        """
        Determine what `pdf_bytes` requires.

        `schema_photo`/`schema_signature` are the form JSON's declaration, used
        when there is no PDF to read AND as a floor when there is: a form that
        declares a photo box still requires one even if the caption could not be
        located, so the user is asked rather than silently skipped.

        Never raises for content problems — an unreadable PDF simply falls back
        to the schema declaration.
        """
        if not pdf_bytes or not pdf_bytes[:5].startswith(b"%PDF"):
            return FormAssetRequirements(
                photo=schema_photo, signature=schema_signature, detected_from="schema"
            )
        try:
            photo_regions, signature_regions = self._scan(pdf_bytes)
        except Exception:  # noqa: BLE001 - detection must never block an upload
            logger.exception("Form asset detection failed; using schema declaration")
            return FormAssetRequirements(
                photo=schema_photo, signature=schema_signature, detected_from="schema"
            )

        requirements = FormAssetRequirements(
            photo=bool(photo_regions) or schema_photo,
            signature=bool(signature_regions) or schema_signature,
            photo_regions=photo_regions,
            signature_regions=signature_regions,
            detected_from="document",
        )
        logger.info(
            "Form assets detected: photo=%s (%d region(s)) signature=%s (%d region(s))",
            requirements.photo,
            len(photo_regions),
            requirements.signature,
            len(signature_regions),
        )
        return requirements

    # ------------------------------------------------------------------ #
    # Scanning
    # ------------------------------------------------------------------ #

    def _scan(
        self, pdf_bytes: bytes
    ) -> tuple[tuple[AssetRegion, ...], tuple[AssetRegion, ...]]:
        """Widgets first, then printed captions; both merged and ranked."""
        photo: list[AssetRegion] = []
        signature: list[AssetRegion] = []
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            for page in document:
                self._scan_widgets(page, photo, signature)
                self._scan_layout(page, photo, signature)
        finally:
            document.close()

        # Best evidence first: an AcroForm widget always outranks a caption
        # guess, then the more explicit caption wins.
        def rank(region: AssetRegion) -> tuple[int, int]:
            return (1 if region.source == "acroform" else 0, region.score)

        photo.sort(key=rank, reverse=True)
        signature.sort(key=rank, reverse=True)
        return tuple(photo), tuple(signature)

    def _scan_widgets(
        self,
        page: "fitz.Page",
        photo: list[AssetRegion],
        signature: list[AssetRegion],
    ) -> None:
        """Real form widgets — the author's own named boxes."""
        try:
            widgets = list(page.widgets() or [])
        except Exception:  # noqa: BLE001 - malformed AcroForm
            return
        for widget in widgets:
            name = (widget.field_name or "").strip()
            if not name:
                continue
            if _PHOTO_ADJACENT_SIGNATURE.search(name):
                # "sign_across_photo" widget: a photo instruction, never the
                # signature field.
                continue
            rect = widget.rect
            photo_score = _score_caption(name, _PHOTO_CAPTIONS)
            signature_score = _score_caption(name, _SIGNATURE_CAPTIONS)
            # A name can score on both ("photo_signature"); the stronger wins,
            # so the value is never written into two different boxes.
            if photo_score and photo_score >= signature_score:
                photo.append(
                    AssetRegion(
                        page=page.number,
                        x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1,
                        source="acroform", matched_text=name, score=photo_score,
                    )
                )
            elif signature_score:
                signature.append(
                    AssetRegion(
                        page=page.number,
                        x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1,
                        source="acroform", matched_text=name, score=signature_score,
                    )
                )

    def _scan_layout(
        self,
        page: "fitz.Page",
        photo: list[AssetRegion],
        signature: list[AssetRegion],
    ) -> None:
        """Flat forms: find the printed caption and infer the box around it."""
        try:
            blocks = page.get_text("blocks") or []
        except Exception:  # noqa: BLE001
            return
        page_rect = page.rect
        for block in blocks:
            if len(block) < 5:
                continue
            x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], str(block[4])
            if not text.strip() or _INSTRUCTION.search(text):
                continue
            if len(text.split()) > _MAX_CAPTION_WORDS:
                continue  # prose, not a field caption

            photo_score = _score_caption(text, _PHOTO_CAPTIONS)
            signature_score = _score_caption(text, _SIGNATURE_CAPTIONS)

            if _PHOTO_ADJACENT_SIGNATURE.search(text):
                # "Sign across the photograph" identifies the PHOTO box and
                # must never contribute a signature region.
                signature_score = 0
                photo_score = max(photo_score, 4)

            if photo_score and photo_score >= signature_score:
                region = self._photo_box(page_rect, x0, y0, x1, y1)
                if region is not None:
                    photo.append(
                        AssetRegion(
                            page=page.number,
                            x0=region[0], y0=region[1], x1=region[2], y1=region[3],
                            source="layout",
                            matched_text=text.strip()[:80],
                            score=photo_score,
                        )
                    )
            elif signature_score:
                region = self._signature_box(page_rect, x0, y0, x1, y1)
                if region is not None:
                    signature.append(
                        AssetRegion(
                            page=page.number,
                            x0=region[0], y0=region[1], x1=region[2], y1=region[3],
                            source="layout",
                            matched_text=text.strip()[:80],
                            score=signature_score,
                        )
                    )

    @staticmethod
    def _photo_box(
        page_rect: "fitz.Rect", x0: float, y0: float, x1: float, y1: float
    ) -> tuple[float, float, float, float] | None:
        """
        The photo box for a located caption.

        Photo captions are usually printed INSIDE the box they describe ("Affix
        recent photograph" sits in the middle of an empty rectangle), so the
        caption's own block is the box when it is plausibly photo-shaped.
        Otherwise a passport-sized area is reserved below the caption.
        """
        width, height = x1 - x0, y1 - y0
        if _MIN_PHOTO_SIDE <= width <= _MAX_PHOTO_SIDE and height >= _MIN_PHOTO_SIDE:
            return (x0, y0, x1, y1)
        # Caption is a thin one-line label: reserve a standard box under it,
        # clamped to the page so nothing is ever drawn off-canvas.
        box_w = min(110.0, page_rect.width - x0 - 8)
        box_h = min(140.0, page_rect.height - y1 - 8)
        if box_w < _MIN_PHOTO_SIDE or box_h < _MIN_PHOTO_SIDE:
            return None
        return (x0, y1 + 2.0, x0 + box_w, y1 + 2.0 + box_h)

    @staticmethod
    def _signature_box(
        page_rect: "fitz.Rect", x0: float, y0: float, x1: float, y1: float
    ) -> tuple[float, float, float, float] | None:
        """
        The signature area for a located caption.

        A signature caption ("Signature of Applicant") is printed BELOW or
        beside the line that is signed, so the usable area is the clear space
        directly ABOVE the caption.
        """
        height = max(18.0, min(46.0, (y1 - y0) * 3))
        top = y0 - height - 2.0
        if top < 0:
            # Caption sits at the very top of the page: use the space below it.
            top = y1 + 2.0
            if top + height > page_rect.height:
                return None
        width = max(80.0, min(200.0, x1 - x0))
        if x0 + width > page_rect.width:
            width = page_rect.width - x0 - 4
        if width < 40.0:
            return None
        return (x0, top, x0 + width, top + height)


# Stateless singleton — safe to share across requests.
form_asset_detector = FormAssetDetector()
