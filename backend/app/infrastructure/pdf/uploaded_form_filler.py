"""
UploadedFormFiller (Phase 13) — fill the user's OWN uploaded KYC form.

The bundled CVL coordinate map can only ever produce a CVL page. When the user
uploads an SBI/HDFC/ICICI/Axis (or any other) form, the completed output must
be THAT document — same layout, same legal text, same branding — with the
answers written onto it. Nothing is recreated and the uploaded file itself is
never modified: this adapter always returns NEW bytes.

Two strategies, tried in order, both layout-driven rather than coordinate-table
driven so an unseen form works without a hand-measured map:

  1. ACROFORM — the PDF carries real form widgets. Their field names are
     matched semantically against the document schema's labels, then set
     directly (text, checkbox, radio). Highest fidelity: the value lands in
     the box the form's author defined.

  2. TEXT-LAYOUT — a flat/scanned form. Every word's bounding box is read
     from the page, the schema's printed label is located, and the value is
     drawn in the clear space that follows it. Choice options are found the
     same way and ticked. Coordinates are DISCOVERED per document, so a
     differently positioned field on an unseen form is still handled.

Anything that cannot be placed is reported, never guessed at.
"""

import logging
import re

import fitz  # PyMuPDF

from app.domain.form_assets import (
    ASSET_FIELD_IDS as _ASSET_FIELD_IDS,
    AssetKind,
    AssetRegion,
    FormAssetRequirements,
)
from app.domain.intelligence import DocumentSchema

logger = logging.getLogger(__name__)

# A value is drawn this far right of its label's right edge.
_LABEL_GAP = 4.0
# Never run a drawn value past this fraction of the page width.
_RIGHT_MARGIN = 24.0
_FONT_SIZE = 8.5
_TICK_SIZE = 7.0

# Words that make a located label a printed instruction rather than a field.
_INSTRUCTION = re.compile(r"please|refer|guideline|overleaf|instruction", re.I)


class FilledField:
    """One successfully written field (for reporting/counting)."""

    __slots__ = ("field_id", "page", "strategy")

    def __init__(self, field_id: str, page: int, strategy: str) -> None:
        self.field_id = field_id
        self.page = page
        self.strategy = strategy


class UploadedFormFiller:
    """Write canonical answers onto the user's uploaded form PDF."""

    def fill(
        self,
        pdf_bytes: bytes,
        values: dict[str, str],
        labels: dict[str, tuple[str, ...]],
        options: dict[str, dict[str, tuple[str, ...]]],
        schema: DocumentSchema | None = None,
        assets: dict[AssetKind, bytes] | None = None,
        asset_requirements: FormAssetRequirements | None = None,
    ) -> tuple[bytes, list[FilledField], list[str]]:
        """
        Fill `values` (field_id -> value) onto a copy of `pdf_bytes`.

        `labels`  — field_id -> printed captions to search for.
        `options` — field_id -> {option value -> captions} for tick controls.
        `assets`  — photo/signature image bytes to place.
        `asset_requirements` — the regions those images belong in, discovered
                    from THIS document by FormAssetDetector.

        Returns (new pdf bytes, filled fields, unplaced field ids). Raises
        nothing for content problems: an unfillable field is simply reported.
        """
        # Asset fields hold an opaque asset id, not printable text. They are
        # withheld from both text strategies — writing "a3f9c2…" onto the
        # signature line is worse than leaving it blank — and satisfied only by
        # the image placement below.
        asset_field_ids = set(_ASSET_FIELD_IDS.values())
        text_values = {k: v for k, v in values.items() if k not in asset_field_ids}

        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            filled: list[FilledField] = []
            done: set[str] = set()

            # 1. Real form widgets first — the author's own field definitions.
            self._fill_widgets(document, text_values, labels, options, filled, done)

            # 2. Whatever is left: locate the printed label and write beside it.
            remaining = {k: v for k, v in text_values.items() if k not in done}
            if remaining:
                self._fill_by_layout(
                    document, remaining, labels, options, filled, done
                )

            # 3. Images last, so a photo is never overwritten by text drawn
            #    into the same area afterwards.
            if assets:
                self._place_assets(
                    document, assets, asset_requirements, filled, done
                )

            unplaced = [k for k in values if k not in done]
            output = document.tobytes(deflate=True, garbage=3)
        finally:
            document.close()

        logger.info(
            "Uploaded-form fill (%s): %d/%d fields placed (%s), %d unplaced",
            schema.id if schema else "unknown-schema",
            len(filled),
            len(values),
            ", ".join(sorted({f.strategy for f in filled})) or "none",
            len(unplaced),
        )
        return output, filled, unplaced

    # ------------------------------------------------------------------ #
    # Strategy 1 — AcroForm widgets
    # ------------------------------------------------------------------ #

    def _fill_widgets(
        self,
        document: "fitz.Document",
        values: dict[str, str],
        labels: dict[str, tuple[str, ...]],
        options: dict[str, dict[str, tuple[str, ...]]],
        filled: list[FilledField],
        done: set[str],
    ) -> None:
        for page in document:
            try:
                widgets = list(page.widgets() or [])
            except Exception:  # noqa: BLE001 - malformed AcroForm, fall through
                continue
            for widget in widgets:
                name = (widget.field_name or "").strip()
                if not name:
                    continue
                field_id = self._match_field(name, values, labels, done)
                if field_id is None:
                    continue
                value = values[field_id]
                try:
                    if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                        if not self._option_matches(field_id, value, name, options):
                            continue
                        widget.field_value = True
                    elif widget.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                        if not self._option_matches(field_id, value, name, options):
                            continue
                        widget.field_value = name
                    else:
                        widget.field_value = value
                    widget.update()
                except Exception:  # noqa: BLE001 - one bad widget must not stop the rest
                    logger.debug("Widget %r rejected value for %s", name, field_id)
                    continue
                done.add(field_id)
                filled.append(FilledField(field_id, page.number + 1, "acroform"))

    @staticmethod
    def _match_field(
        widget_name: str,
        values: dict[str, str],
        labels: dict[str, tuple[str, ...]],
        done: set[str],
    ) -> str | None:
        """Semantic match of an AcroForm field name to one of our field ids."""
        normalized = re.sub(r"[\W_]+", " ", widget_name).strip().lower()
        if not normalized:
            return None
        best: tuple[int, str] | None = None
        for field_id in values:
            if field_id in done:
                continue
            candidates = (field_id.replace("_", " "), *labels.get(field_id, ()))
            for candidate in candidates:
                cand = re.sub(r"[\W_]+", " ", candidate).strip().lower()
                if not cand:
                    continue
                if normalized == cand or cand in normalized or normalized in cand:
                    # Longer matches are more specific ("father name" beats "name").
                    score = len(cand)
                    if best is None or score > best[0]:
                        best = (score, field_id)
        return best[1] if best else None

    @staticmethod
    def _option_matches(
        field_id: str,
        value: str,
        widget_name: str,
        options: dict[str, dict[str, tuple[str, ...]]],
    ) -> bool:
        """Should this tick-box be checked for the chosen option value?"""
        captions = options.get(field_id, {}).get(value.lower())
        if not captions:
            # Booleans: tick when the answer is affirmative.
            return value.strip().lower() in {"yes", "true"}
        name = re.sub(r"[\W_]+", " ", widget_name).lower()
        return any(re.sub(r"[\W_]+", " ", c).lower() in name for c in captions)


    # ------------------------------------------------------------------ #
    # Image assets — photograph and signature
    # ------------------------------------------------------------------ #

    def _place_assets(
        self,
        document: "fitz.Document",
        assets: dict[AssetKind, bytes],
        requirements: FormAssetRequirements | None,
        filled: list[FilledField],
        done: set[str],
    ) -> None:
        """
        Draw the photograph and signature into the regions detected for THIS
        document.

        Each asset goes into AT MOST ONE region — the best-ranked one. That is
        the whole point: a KYC form prints several signature-ish captions
        ("Signature of Applicant", "Sign across the photograph", a witness
        line), and stamping the signature into all of them would deface the
        page. FormAssetDetector has already excluded the photo-adjacent
        captions and scored the rest; here we simply trust the winner.

        No region means no placement. A signature is never dropped at a guessed
        coordinate — an unplaced asset is reported so the user can add it by
        hand, which is far better than one printed across their own face.
        """
        if requirements is None:
            logger.info("No asset regions detected; photo/signature not placed")
            return

        for kind, image_bytes in assets.items():
            if not image_bytes:
                continue
            field_id = _ASSET_FIELD_IDS[kind]
            region = self._best_region(document, requirements.regions(kind))
            if region is None:
                logger.info(
                    "No %s region found on the uploaded form; not placed", kind.value
                )
                continue
            try:
                page = document[region.page]
                target = self._fit_preserving_aspect(image_bytes, region)
                if target is None:
                    continue
                page.insert_image(target, stream=image_bytes, keep_proportion=True)
            except Exception:  # noqa: BLE001 - a bad image must not fail the PDF
                logger.exception("Could not place %s on the form", kind.value)
                continue
            done.add(field_id)
            filled.append(
                FilledField(field_id, region.page + 1, f"image-{region.source}")
            )
            logger.info(
                "Placed %s on page %d via %s (%r)",
                kind.value, region.page + 1, region.source, region.matched_text[:40],
            )

    @staticmethod
    def _best_region(
        document: "fitz.Document", regions: tuple[AssetRegion, ...]
    ) -> AssetRegion | None:
        """
        The single region an asset is written into.

        Regions arrive pre-ranked (AcroForm widgets first, then by caption
        specificity), so this only has to reject ones that no longer address a
        real page or have collapsed to nothing.
        """
        for region in regions:
            if 0 <= region.page < document.page_count:
                if region.width >= 8.0 and region.height >= 8.0:
                    return region
        return None

    @staticmethod
    def _fit_preserving_aspect(
        image_bytes: bytes, region: AssetRegion
    ) -> "fitz.Rect | None":
        """
        Centre the image inside its region without distorting it.

        A stretched photograph looks forged, and a stretched signature stops
        matching the one on file — so the image is letterboxed into the box
        rather than made to fill it.
        """
        try:
            pixmap = fitz.Pixmap(image_bytes)
            source_w, source_h = float(pixmap.width), float(pixmap.height)
        except Exception:  # noqa: BLE001
            return None
        if source_w <= 0 or source_h <= 0:
            return None

        scale = min(region.width / source_w, region.height / source_h)
        draw_w, draw_h = source_w * scale, source_h * scale
        offset_x = region.x0 + (region.width - draw_w) / 2
        offset_y = region.y0 + (region.height - draw_h) / 2
        return fitz.Rect(offset_x, offset_y, offset_x + draw_w, offset_y + draw_h)

    # ------------------------------------------------------------------ #
    # Strategy 2 — printed-label layout
    # ------------------------------------------------------------------ #

    def _fill_by_layout(
        self,
        document: "fitz.Document",
        values: dict[str, str],
        labels: dict[str, tuple[str, ...]],
        options: dict[str, dict[str, tuple[str, ...]]],
        filled: list[FilledField],
        done: set[str],
    ) -> None:
        for page in document:
            if len(done) == len(values):
                break
            words = page.get_text("words") or []
            if not words:
                continue  # image-only page: nothing locatable without OCR
            page_width = page.rect.width

            for field_id, value in values.items():
                if field_id in done:
                    continue
                choice_captions = options.get(field_id)
                if choice_captions:
                    if self._tick_option(
                        page, words, value, choice_captions, field_id
                    ):
                        done.add(field_id)
                        filled.append(
                            FilledField(field_id, page.number + 1, "layout-tick")
                        )
                    continue
                anchor = self._find_label(words, labels.get(field_id, ()))
                if anchor is None:
                    continue
                x0, y0, x1, y1 = anchor
                # Write immediately after the label, on its baseline.
                start = x1 + _LABEL_GAP
                budget = page_width - _RIGHT_MARGIN - start
                if budget < 30:
                    continue  # no room: leave it for a human rather than overlap
                text = self._fit(value, budget)
                page.insert_text(
                    fitz.Point(start, y1 - 1.5),
                    text,
                    fontsize=_FONT_SIZE,
                    fontname="helv",
                    color=(0, 0, 0.55),
                )
                done.add(field_id)
                filled.append(FilledField(field_id, page.number + 1, "layout-text"))

    def _tick_option(
        self,
        page: "fitz.Page",
        words: list,
        value: str,
        captions: dict[str, tuple[str, ...]],
        field_id: str,
    ) -> bool:
        """Find the chosen option's printed caption and tick the box beside it."""
        wanted = captions.get(value.lower())
        if not wanted:
            if value.strip().lower() not in {"yes", "true"}:
                return True  # a 'no' answer legitimately leaves the box empty
            wanted = captions.get("yes", ())
        anchor = self._find_label(words, wanted)
        if anchor is None:
            return False
        x0, y0, x1, y1 = anchor
        # The control sits immediately left of its caption on every one of
        # these forms; drop the tick there.
        page.insert_text(
            fitz.Point(max(2.0, x0 - _TICK_SIZE - 2.0), y1 - 1.0),
            "X",
            fontsize=_TICK_SIZE,
            fontname="helv",
            color=(0, 0, 0.55),
        )
        return True

    @staticmethod
    def _find_label(
        words: list, captions: tuple[str, ...]
    ) -> tuple[float, float, float, float] | None:
        """
        Locate a printed caption in the page's word boxes.

        Words are matched as a consecutive run so multi-word captions
        ("Father's Name") are found even though the extractor returns each
        word separately. Longest caption wins — it is the most specific.
        """
        if not words:
            return None
        tokens = [
            (re.sub(r"[^a-z0-9]", "", w[4].lower()), w[0], w[1], w[2], w[3])
            for w in words
        ]
        best: tuple[int, tuple[float, float, float, float]] | None = None
        for caption in sorted(captions, key=len, reverse=True):
            if _INSTRUCTION.search(caption):
                continue
            wanted = [re.sub(r"[^a-z0-9]", "", p) for p in caption.lower().split()]
            wanted = [p for p in wanted if p]
            if not wanted:
                continue
            for i in range(len(tokens) - len(wanted) + 1):
                window = tokens[i : i + len(wanted)]
                # Prefix match in EITHER direction so a caption printed
                # "Father's/Spouse Name" still matches an alias written
                # "Father's/Spouse's Name" (singular vs plural, abbreviations).
                if all(
                    w[0] and (w[0].startswith(t) or t.startswith(w[0]))
                    for w, t in zip(window, wanted)
                ):
                    # Same visual line only (guards against a coincidental
                    # vertical run of words).
                    if abs(window[0][2] - window[-1][2]) > 4:
                        continue
                    box = (
                        window[0][1],
                        min(w[2] for w in window),
                        max(w[3] for w in window),
                        max(w[4] for w in window),
                    )
                    score = len(caption)
                    if best is None or score > best[0]:
                        best = (score, box)
                    break
        return best[1] if best else None

    @staticmethod
    def _fit(value: str, budget: float) -> str:
        """Trim a value to the horizontal space actually available."""
        max_chars = max(4, int(budget / (_FONT_SIZE * 0.5)))
        text = value.strip()
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


# Stateless singleton.
uploaded_form_filler = UploadedFormFiller()
