"""
FormPlacementEngine — write answers onto the user's own uploaded KYC form.

Replaces the caption-and-hope filler that produced overlapping, misplaced text.
Every placement now resolves to a BOUNDED RECTANGLE before a single glyph is
drawn, and anything that cannot be resolved is skipped and reported.

The four rules that fix the observed corruption:

  1. ONE TARGET RECTANGLE PER VALUE. A value is drawn inside a rectangle, never
     "after a label until the page runs out". Overflow into the next field is
     therefore impossible by construction.

  2. OCCUPANCY IS TRACKED. Every rectangle that gets written — and every piece
     of text already printed on the page — is recorded. A candidate that
     collides with either is rejected. This is what stops the date of birth and
     the mobile number sharing one baseline as "12-03-2009876823678".

  3. MATCHING IS EXACT, NOT FUZZY. Captions match on whole normalised tokens.
     The old bidirectional prefix test (`w.startswith(t) or t.startswith(w)`)
     let the page token "p.a." match the caption "pan", which is how a PAN
     ended up on the "Specify reason" line. Widget names match exactly too.

  4. UNCERTAIN MEANS SKIP. A blank field a human can complete is strictly
     better than a confident-looking wrong value they may never check.

Photograph and signature get dedicated treatment: they are validated for mutual
non-overlap, the signature is never allowed inside the photo box, and
official-use signature areas (branch, employee, acknowledgement) are excluded
outright — filling those would forge a bank officer's certification.
"""

import logging
import re

import fitz  # PyMuPDF

from app.domain.form_assets import ASSET_FIELD_IDS, AssetKind, FormAssetRequirements
from app.domain.form_layout import (
    AnchorMode,
    FieldPlacement,
    FormLayout,
    PlacementMode,
    PlacementSource,
    Rect,
)

logger = logging.getLogger(__name__)

_FONT = "helv"
_MAX_FONT = 9.0
_MIN_FONT = 5.0
_PADDING = 1.5
_INK = (0.05, 0.05, 0.45)

# Captions that mark an official-use area. A value drawn in one of these is
# never merely untidy — it impersonates a bank employee's certification.
_OFFICIAL_USE = re.compile(
    r"for\s+(bank|office|branch)\s+use|office\s+use\s+only|branch\s+declaration"
    r"|employee\s+signature|signature\s+&?\s*branch\s+stamp|branch\s+stamp"
    r"|attestation|acknowledge?ment\s+copy|for\s+bank\s+use|emp\.?\s*(name|code)"
    r"|kyc\s+verification\s+carried\s+out|institution\s+name\s+and\s+stamp"
    r"|in-?person\s+verification|maker|checker",
    re.I,
)


class PlacedField:
    """One value successfully written (for reporting and counting)."""

    __slots__ = ("field_id", "page", "source", "rect")

    def __init__(
        self, field_id: str, page: int, source: PlacementSource, rect: Rect
    ) -> None:
        self.field_id = field_id
        self.page = page
        self.source = source
        self.rect = rect


class SkippedField:
    """One value deliberately NOT written, with the reason why."""

    __slots__ = ("field_id", "reason")

    def __init__(self, field_id: str, reason: str) -> None:
        self.field_id = field_id
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.field_id}({self.reason})"


class _PageOccupancy:
    """
    What is already on a page, so nothing is drawn on top of it.

    Seeded with the form's own printed text (captions, rules, instructions) and
    grown with every value placed. Without this the engine happily stacks two
    answers on the same baseline.
    """

    def __init__(self, page: "fitz.Page") -> None:
        self._printed: list[Rect] = []
        self._placed: list[Rect] = []
        for word in page.get_text("words") or []:
            text = word[4]
            # Blank-field placeholders ("____", "__ __", "......") are printed
            # text that MARKS where a value goes. Treating them as occupied
            # would block every field they decorate — which is most of a KYC
            # form. They are ruled out of occupancy entirely.
            if not re.sub(r"[\W_]+", "", text):
                continue
            self._printed.append(
                Rect(x0=word[0], y0=word[1], x1=word[2], y1=word[3])
            )

    def is_free(self, rect: Rect, ignore_printed: bool = False) -> bool:
        """
        True when `rect` collides with nothing already there.

        `ignore_printed` is used for MANIFEST rectangles: those were measured
        against this exact form by a human, so they are allowed to sit over
        printed hint text ("D D M M Y Y Y Y" inside a date comb). They are
        still checked against values already placed — two answers must never
        share a box, whatever the source.
        """
        if not ignore_printed and any(rect.overlaps(t) for t in self._printed):
            return False
        return not any(rect.overlaps(t) for t in self._placed)

    def reserve(self, rect: Rect) -> None:
        self._placed.append(rect)

    def free_width_from(self, x: float, y0: float, y1: float, limit: float) -> float:
        """
        How far right of `x` the space stays clear on this line.

        This is the measurement the old engine never made: it used the page
        margin as the bound, so a long value ran straight through whatever came
        next. Here the value is clipped to the real gap.
        """
        nearest = limit
        for taken in self._printed:
            if taken.x0 <= x:
                continue
            if taken.y1 <= y0 + 1 or taken.y0 >= y1 - 1:
                continue  # different line
            nearest = min(nearest, taken.x0)
        return max(0.0, nearest - x - _PADDING)


def _spans_edges(keep, x: int, y: int, width: int, height: int) -> bool:
    """Does the kept run through (x, y) reach both edges of the region?"""
    row = keep[y]
    if row[0] and row[width - 1] and all(row[i] for i in range(width)):
        return True
    return all(keep[i][x] for i in range(height))


_DATE_PARTS = re.compile(r"^\s*(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{2,4})\s*$")


def _format_date(value: str, layout: str) -> str | None:
    """
    Re-render a date into a form's own box layout ("DDMMYY", "DDMMYYYY").

    Returns None when the value is not a recognisable D-M-Y date, so the caller
    leaves the field alone rather than writing something malformed. A two-digit
    input year is expanded on the usual pivot; the output year is then taken
    from the full four digits, which is what makes "19-07-2026" render as
    "190726" instead of losing the century.
    """
    match = _DATE_PARTS.match(value)
    if match is None:
        return None
    day, month, year = match.groups()
    if len(year) == 2:
        year = ("20" + year) if int(year) < 50 else ("19" + year)
    if len(year) != 4:
        return None
    parts = {"YYYY": year, "YY": year[-2:], "DD": day.zfill(2), "MM": month.zfill(2)}
    rendered = layout
    for token in ("YYYY", "YY", "DD", "MM"):   # YYYY before YY, deliberately
        rendered = rendered.replace(token, parts[token])
    return rendered


def _comb_text(value: str, placement: "FieldPlacement | None") -> str:
    """
    A value prepared for comb layout, WITHOUT truncating it to the cell count.

    The same preparation `_draw_comb` performs, factored out so capacity can be
    judged on the exact string that would be drawn rather than on the raw
    answer — "01-01-1966" is ten characters but only eight cells' worth.
    """
    text = value
    if placement is not None and placement.date_format:
        text = _format_date(value, placement.date_format) or value
    strip = placement.strip_separators if placement is not None else True
    return (
        re.sub(r"[^A-Za-z0-9]", "", text.strip())
        if strip
        else re.sub(r"\s+", " ", text.strip())
    )


def _fits_as_text(text: str, rect: Rect) -> bool:
    """True when `text` can be drawn in `rect` without dropping characters."""
    usable = max(1.0, rect.width - 2 * _PADDING)
    return fitz.get_text_length(text, fontname=_FONT, fontsize=_MIN_FONT) <= usable


def _same_value(left: str, right: str) -> bool:
    """
    Are these the same answer, ignoring presentation?

    Case, spacing and separators differ constantly between what a person typed
    on a form and what the pipeline extracted ("01-01-1966" vs "01011966",
    "Sinnar" vs "SINNAR"). Treating those as different values causes the engine
    to "replace" a value with itself, which is both pointless and destructive.
    """
    return (
        re.sub(r"[^a-z0-9]", "", left.lower())
        == re.sub(r"[^a-z0-9]", "", right.lower())
    )


def _normalize(text: str) -> list[str]:
    """Split into comparable lowercase alphanumeric tokens."""
    return [t for t in re.sub(r"[^a-z0-9]+", " ", text.lower()).split() if t]


class FormPlacementEngine:
    """Draw validated answers onto a copy of the user's uploaded form."""

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def fill(
        self,
        pdf_bytes: bytes,
        values: dict[str, str],
        labels: dict[str, tuple[str, ...]],
        options: dict[str, dict[str, tuple[str, ...]]],
        layout: FormLayout | None = None,
        assets: dict[AssetKind, bytes] | None = None,
        asset_requirements: FormAssetRequirements | None = None,
    ) -> tuple[bytes, list[PlacedField], list[SkippedField]]:
        """
        Fill `values` onto a COPY of `pdf_bytes`; the original is never touched.

        Returns (new bytes, placed fields, skipped fields with reasons).
        """
        asset_field_ids = set(ASSET_FIELD_IDS.values())
        text_values = {k: v for k, v in values.items() if k not in asset_field_ids and v}

        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        placed: list[PlacedField] = []
        skipped: list[SkippedField] = []
        try:
            # Prove the upload IS the layout these rectangles were measured
            # against before writing a single glyph. A form whose sections
            # repeat identically (Axis CK001) gives a shifted copy no way to
            # announce itself, so a landmark is checked instead of assumed.
            if layout is not None and not self._layout_verified(document, layout):
                for field_id in text_values:
                    skipped.append(SkippedField(field_id, "layout-unverified"))
                for kind in assets or {}:
                    skipped.append(
                        SkippedField(ASSET_FIELD_IDS[kind], "layout-unverified")
                    )
                return pdf_bytes, placed, skipped

            occupancy = {n: _PageOccupancy(document[n]) for n in range(document.page_count)}
            widgets = self._index_widgets(document, layout)

            # Placement runs in two passes so that REPLACING a value already on
            # a partially-filled form is safe. Redactions erase everything in
            # their rectangle, so every removal must happen before the first
            # glyph is drawn - otherwise a value written early would be wiped
            # out by a redaction resolved later.
            pending_redactions: dict[int, list[Rect]] = {}
            # Scanned pages cannot be redacted; their old values are cleared
            # pixel-wise instead, and a clear that cannot be done safely
            # withdraws its field from the draw list.
            pending_raster_clears: dict[int, list[tuple]] = {}
            pending_draws: list[tuple] = []

            for field_id, value in text_values.items():
                self._place_value(
                    document, occupancy, widgets, layout, labels, options,
                    field_id, value, placed, skipped,
                    pending_redactions, pending_draws, pending_raster_clears,
                )

            self._apply_redactions(document, pending_redactions, skipped, pending_draws)
            self._apply_raster_clears(
                document, pending_raster_clears, skipped, pending_draws
            )

            for (
                page_no, rect, value, mode, placement, field_id, source, report
            ) in pending_draws:
                if mode is PlacementMode.COMB and placement and placement.cells:
                    # A form that gives a date fewer boxes than DD-MM-YYYY needs
                    # gets it re-rendered to its own layout first; without this
                    # the plain strip-and-truncate turns 2026 into 20.
                    text = value
                    if placement.date_format:
                        text = _format_date(value, placement.date_format) or value
                    self._draw_comb(
                        document[page_no], rect, text, placement.cells,
                        strip=placement.strip_separators,
                    )
                elif mode is PlacementMode.MULTILINE:
                    self._draw_wrapped(document[page_no], rect, value)
                else:
                    self._draw_fitted(document[page_no], rect, value)
                # A name split across First/Middle/Last queues three draws for
                # ONE answer; only the first reports, so "fields filled" counts
                # fields rather than boxes.
                if report:
                    placed.append(PlacedField(field_id, page_no, source, rect))

            if assets:
                self._place_assets(
                    document, occupancy, widgets, layout, assets,
                    asset_requirements, placed, skipped,
                )

            output = document.tobytes(deflate=True, garbage=3)
        finally:
            document.close()

        logger.info(
            "Placement (%s): %d placed, %d skipped [%s]",
            layout.form_id if layout else "no-manifest",
            len(placed), len(skipped),
            ", ".join(f"{s.field_id}:{s.reason}" for s in skipped[:8]),
        )
        return output, placed, skipped

    # ------------------------------------------------------------------ #
    # Widgets
    # ------------------------------------------------------------------ #

    def _layout_verified(self, document: "fitz.Document", layout: FormLayout) -> bool:
        """
        True when every landmark the manifest declares is where it should be.

        A form with no guards is trivially verified, which is every form whose
        sections cannot be mistaken for one another.
        """
        for guard in layout.layout_guards:
            if guard.page >= document.page_count:
                logger.warning(
                    "Layout guard %r: page %d missing (%d pages)",
                    guard.anchor, guard.page + 1, document.page_count,
                )
                return False
            hits = self._find_caption(document[guard.page], guard.anchor)
            if len(hits) <= guard.occurrence:
                logger.warning(
                    "Layout guard %r: heading not found on page %d; refusing "
                    "to place anything on an unrecognised layout",
                    guard.anchor, guard.page + 1,
                )
                return False
            top = hits[guard.occurrence][1]
            if not (guard.min_y <= top <= guard.max_y):
                logger.warning(
                    "Layout guard %r: heading at y=%.1f, expected %.1f-%.1f; "
                    "the upload is not the measured layout",
                    guard.anchor, top, guard.min_y, guard.max_y,
                )
                return False
        return True

    @staticmethod
    def _index_widgets(document: "fitz.Document", layout: FormLayout | None) -> dict:
        """
        Map exact widget short-name -> (page, full field name, rectangle).

        Names are matched on their LAST dotted segment, so ICICI's XFA-style
        'topmostSubform[0].Page1[0].per_in_cust_name[0]' is addressed as
        'per_in_cust_name'.

        Only plain data is stored, never the Widget object itself: PyMuPDF
        Widgets stop being valid once page iteration moves on, and assigning to
        a stale one fails silently. That is why every ICICI field reported
        "widget-missing" while all 133 widgets were present and settable. The
        live widget is re-fetched from its page at write time instead.
        """
        index: dict[str, tuple[int, str, Rect]] = {}
        for page in document:
            try:
                page_widgets = list(page.widgets() or [])
            except Exception:  # noqa: BLE001 - malformed AcroForm
                continue
            for widget in page_widgets:
                raw = (widget.field_name or "").strip()
                if not raw:
                    continue
                short = re.sub(r"\[\d+\]$", "", raw.split(".")[-1]).strip()
                if not short:
                    continue
                if layout is not None and layout.is_excluded_widget(short):
                    continue  # official use only — never written
                r = widget.rect
                index.setdefault(
                    short,
                    (page.number, raw, Rect(x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)),
                )
        return index

    @staticmethod
    def _live_widget(document, page_no: int, field_name: str):
        """
        Re-fetch a widget from its page, returning (page, widget).

        The PAGE is returned deliberately so the caller holds a reference to
        it. A Widget keeps only a weak link to its page, so if the page object
        is garbage-collected the next write fails with "Annot is not bound to a
        page" - which is exactly what silently blanked every ICICI field.
        """
        try:
            page = document[page_no]
            for widget in page.widgets() or []:
                if (widget.field_name or "") == field_name:
                    return page, widget
        except Exception:  # noqa: BLE001
            return None
        return None

    # ------------------------------------------------------------------ #
    # Value placement
    # ------------------------------------------------------------------ #

    def _place_value(
        self, document, occupancy, widgets, layout, labels, options,
        field_id: str, value: str,
        placed: list[PlacedField], skipped: list[SkippedField],
        pending_redactions: dict[int, list[Rect]],
        pending_draws: list[tuple],
        pending_raster_clears: dict[int, list[tuple]],
    ) -> None:
        """Resolve one field to a rectangle and queue it, or skip with a reason."""
        placement = layout.fields.get(field_id) if layout else None

        # Verified absent from this form - not a coverage gap.
        if layout is not None and field_id in layout.not_on_form:
            skipped.append(SkippedField(field_id, "not-on-form"))
            return

        # 1. AcroForm widget — the form author's own box.
        if placement is not None and placement.widget:
            if self._fill_widget(document, widgets, placement, field_id, value, placed):
                return
            skipped.append(SkippedField(field_id, "widget-missing"))
            return

        # Choice fields need a TICK, not text. Without a manifest saying which
        # box to mark, the semantic path would print the machine value beside
        # the label — "resident_individua", truncated and meaningless. A choice
        # the engine cannot tick is left for the human.
        is_choice = field_id in options
        if is_choice:
            # Some forms capture a choice as FREE TEXT rather than tick boxes
            # (SBI's Annexure A prints an empty "Occupation" cell, not a list of
            # options). When the manifest gives such a field a plain rectangle,
            # the option's human LABEL is written into it — the machine value
            # would print "private_sector" on a bank form.
            if (
                placement is not None
                and placement.rect is not None
                and placement.mode is PlacementMode.TEXT
            ):
                # A form-specific short code wins over the generic label,
                # for cells too small to hold the label itself.
                value = placement.option_text.get(value.lower()) or options[
                    field_id
                ].get(value.lower(), (value,))[0]
            elif placement is not None and placement.option_rects:
                if self._tick_rect(
                    document, occupancy, layout, placement, field_id, value, placed
                ):
                    return
                skipped.append(SkippedField(field_id, "option-not-mapped"))
                return
            elif placement is not None and placement.option_anchors:
                if self._tick_option(
                    document, occupancy, layout, placement, field_id, value, placed
                ):
                    return
                skipped.append(SkippedField(field_id, "option-not-found"))
                return
            else:
                # No tick boxes and no text cell mapped: the engine has no way
                # to record this choice, and guessing a box is how printed
                # option words became answers.
                skipped.append(SkippedField(field_id, "choice-needs-manifest"))
                return
            # (the free-text case falls through to normal placement below)

        # A form that prints First / Middle / Last columns instead of one name
        # line needs the value divided before any rectangle is chosen.
        if placement is not None and placement.name_segments is not None:
            self._place_name_segments(
                document, occupancy, layout, placement, field_id, value,
                placed, skipped, pending_redactions, pending_draws,
            )
            return

        # 2/3. A rectangle from the manifest, or one derived from a caption.
        resolved = self._resolve_rect(
            document, occupancy, layout, labels, placement, field_id, value
        )
        if resolved is None:
            skipped.append(SkippedField(field_id, "no-target"))
            return
        page_no, rect, source = resolved

        if layout is not None and layout.is_excluded_region(page_no, rect):
            skipped.append(SkippedField(field_id, "official-use-area"))
            return
        # A manifest rectangle was measured against this form deliberately, so
        # it may sit over the form's own hint text; a caption-derived guess may
        # not. Either way a rectangle already holding a VALUE is never reused —
        # that check is what stops two answers sharing one baseline.
        trusted = source is PlacementSource.MANIFEST_RECT
        if not occupancy[page_no].is_free(rect, ignore_printed=trusted):
            skipped.append(SkippedField(field_id, "occupied"))
            return

        # An uploaded primary form is often PARTIALLY FILLED already. Whatever
        # is inside the target rectangle decides what happens next: leaving it
        # alone, replacing it, or writing into empty space. Skipping this check
        # is what produced "PRASAD NATHE" and "PRASAD SANTOSH NATHE" printed on
        # top of each other.
        existing = self._existing_value(document[page_no], rect)
        if not existing and layout is not None and not layout.has_text_layer:
            # A scan has no text layer, so an empty read here proves nothing.
            # OCR the region itself before deciding the field is free.
            ocr_read = self._ocr_existing_value(document[page_no], rect)
            if ocr_read is None:
                # The strict read is deliberately conservative because Phase 17
                # feeds it into the Canonical Profile, where a misread would be
                # a wrong fact. For deciding REPLACEMENT the bar is lower: the
                # value we write comes from conflict resolution either way, so
                # a shaky read costs at most an unnecessary (and harmless)
                # clear-and-rewrite of the correct value.
                ocr_read = self._ocr_existing_value(
                    document[page_no], rect, min_confidence=32.0
                )
            if ocr_read is None:
                # Genuinely unreadable ink. Writing here could print over the
                # applicant's own handwriting, and an overprinted field cannot
                # be undone by the person reading the form.
                skipped.append(SkippedField(field_id, "existing-content-unknown"))
                return
            existing = ocr_read

        if existing and _same_value(existing, value):
            # (A) The form already says exactly this. Drawing it again would
            # just double-strike the same glyphs.
            skipped.append(SkippedField(field_id, "already-on-form"))
            return

        mode = placement.mode if placement else PlacementMode.TEXT
        # Refuse the box before reserving or redacting it: a value that cannot
        # be written in full must leave the form exactly as it was, not erase
        # what was there in order to print a partial replacement.
        fitted = self._fit_to_box(mode, rect, value, placement)
        if fitted is None:
            skipped.append(SkippedField(field_id, "value-too-long"))
            return
        mode, value = fitted

        if existing and layout is not None and not layout.has_text_layer:
            # (C) on a SCAN. There is no text object to redact, so the old
            # value's pixels are cleared selectively instead — structure kept,
            # glyphs removed. Queued with the other removals so it happens
            # before anything is drawn.
            pending_raster_clears.setdefault(page_no, []).append((rect, field_id))
            pending_draws.append(
                (page_no, rect, value, mode, placement, field_id, source, True)
            )
            occupancy[page_no].reserve(rect)
            return
        if existing:
            # (C) A different value is there and must be REPLACED, not covered.
            # The old text is queued for removal; drawing happens only after
            # every redaction on the page has been applied, so a value written
            # earlier can never be erased by a later one.
            pending_redactions.setdefault(page_no, []).append(rect)
        # (B) blank -> straight to drawing.
        pending_draws.append(
            (page_no, rect, value, mode, placement, field_id, source, True)
        )
        occupancy[page_no].reserve(rect)

    @staticmethod
    def _fit_to_box(
        mode: PlacementMode, rect: Rect, value: str,
        placement: "FieldPlacement | None",
    ) -> tuple[PlacementMode, str] | None:
        """
        Decide how a value can be drawn in `rect` WITHOUT losing characters,
        or None when it cannot be drawn honestly at all.

        Both drawing primitives used to silently drop the overflow: a comb
        sliced the value to its cell count and fitted text chopped characters
        off the end at the minimum font size. On free text that is merely
        lossy, but on a structured value it manufactures a plausible-looking
        FALSEHOOD — a 29-cell box turned the email
        "rajubhai.saheblal.patel@example.com" into "rajubhai.saheblal.patel@examp",
        which is not a truncated address so much as a wrong one, and nothing on
        the page showed that anything had been dropped.

        So capacity is judged before anything is drawn:

          1. It fits the cells       -> comb, exactly as before. Every value on
                                        every existing form takes this path, so
                                        no current output moves.
          2. It does not fit         -> one fitted line across the same box.
                                        A comb spends a whole cell per glyph
                                        while proportional text at the same
                                        width holds roughly three times as
                                        much, so the complete value almost
                                        always survives here - it simply stops
                                        being one-character-per-cell, which is
                                        what a person writing on the paper form
                                        does when their address will not fit
                                        the boxes.
          3. Not even that           -> skip and report. A blank the applicant
                                        can complete beats a value that reads
                                        as true and is not.
        """
        if mode is PlacementMode.COMB and placement is not None and placement.cells:
            text = _comb_text(value, placement)
            if len(text) <= placement.cells:
                return mode, value
            if _fits_as_text(text, rect):
                return PlacementMode.TEXT, text
            return None

        if mode is PlacementMode.TEXT:
            text = value.strip()
            return (mode, value) if _fits_as_text(text, rect) else None

        # MULTILINE wraps and falls back on its own; CHECK and IMAGE carry no
        # text to overflow.
        return mode, value

    @staticmethod
    def _split_name(value: str) -> tuple[str, str, str]:
        """
        A person's name as (first, middle, last), the way the form's columns
        expect it: leading word first, trailing word last, everything else in
        the middle.

        A single word is a FIRST name only. Putting a lone word in the Last
        column would assert a surname the applicant never gave, and these
        columns are read as separate facts by the KYC registry.
        """
        words = value.split()
        if not words:
            return "", "", ""
        if len(words) == 1:
            return words[0], "", ""
        return words[0], " ".join(words[1:-1]), words[-1]

    def _place_name_segments(
        self, document, occupancy, layout, placement: FieldPlacement,
        field_id: str, value: str,
        placed: list[PlacedField], skipped: list[SkippedField],
        pending_redactions: dict[int, list[Rect]],
        pending_draws: list[tuple],
    ) -> None:
        """
        Write one name across the form's First / Middle / Last boxes.

        Each box goes through the same occupancy and already-filled checks a
        single rectangle does, so a partially-filled form still replaces rather
        than overprints. A box whose part is empty (most people have no middle
        name) is simply left alone.
        """
        segments = placement.name_segments
        assert segments is not None  # guarded by the caller
        page_no = placement.page
        if page_no >= document.page_count:
            skipped.append(SkippedField(field_id, "no-target"))
            return

        parts = self._split_name(value)
        boxes = (segments.first, segments.middle, segments.last)
        # Combs cannot be OCR-replaced safely, so this path is for forms with a
        # real text layer; a scan falls through to being reported, not guessed.
        if layout is not None and not layout.has_text_layer:
            skipped.append(SkippedField(field_id, "no-target"))
            return

        queued = False
        blocked = "already-on-form"
        for text, rect in zip(parts, boxes):
            if not text:
                continue
            if layout is not None and layout.is_excluded_region(page_no, rect):
                continue
            if not occupancy[page_no].is_free(rect, ignore_printed=True):
                continue
            existing = self._existing_value(document[page_no], rect)
            if existing and _same_value(existing, text):
                continue
            cell = FieldPlacement(
                page=page_no,
                mode=PlacementMode.COMB,
                cells=segments.cells,
                # Names carry spaces between middle names; stripping them would
                # run two names together into one word.
                strip_separators=False,
            )
            # A name part longer than its column falls back to fitted text
            # rather than losing its tail: "SATYANARAYANAN" must not be filed
            # as "SATYANARAYAN", a different person's name.
            fitted = self._fit_to_box(PlacementMode.COMB, rect, text, cell)
            if fitted is None:
                blocked = "value-too-long"
                continue
            part_mode, part_text = fitted
            if existing:
                pending_redactions.setdefault(page_no, []).append(rect)
            pending_draws.append(
                (
                    page_no, rect, part_text, part_mode, cell, field_id,
                    PlacementSource.MANIFEST_RECT, not queued,
                )
            )
            occupancy[page_no].reserve(rect)
            queued = True

        if not queued:
            skipped.append(SkippedField(field_id, blocked))

    def _fill_widget(
        self, document, widgets, placement: FieldPlacement, field_id: str,
        value: str, placed: list[PlacedField],
    ) -> bool:
        """Set an exactly-named AcroForm widget."""
        entry = widgets.get(placement.widget)
        if placement.mode is PlacementMode.CHECK:
            target = placement.option_widgets.get(value.lower())
            entry = widgets.get(target) if target else None
        if entry is None:
            return False
        page_no, field_name, rect = entry

        live = self._live_widget(document, page_no, field_name)
        if live is None:
            return False
        page, widget = live  # `page` must stay referenced while we write

        # A widget REPLACES its value by definition, so no redaction is needed
        # here — but re-setting an identical value still counts as a no-op and
        # is reported as such, so the two paths agree on what "already on the
        # form" means.
        if placement.mode is not PlacementMode.CHECK:
            try:
                if _same_value(str(widget.field_value or ""), value):
                    placed.append(
                        PlacedField(field_id, page_no, PlacementSource.ACROFORM, rect)
                    )
                    return True
            except Exception:  # noqa: BLE001 - unreadable value: fall through and set
                pass
        try:
            widget.field_value = (
                True if placement.mode is PlacementMode.CHECK else value
            )
            widget.update()
        except Exception as exc:  # noqa: BLE001 - one bad widget must not stop the rest
            logger.warning("Widget %r rejected %s: %s", field_name, field_id, exc)
            return False
        placed.append(
            PlacedField(field_id, page_no, PlacementSource.ACROFORM, rect)
        )
        return True

    def _tick_rect(
        self, document, occupancy, layout, placement: FieldPlacement,
        field_id: str, value: str, placed: list[PlacedField],
    ) -> bool:
        """
        Tick a checkbox at its MEASURED rectangle.

        The only workable strategy on a scanned form: with no text layer there
        is no caption to locate, so the box position is recorded in the
        manifest instead of guessed at runtime.
        """
        # A multi-select answer arrives comma-separated ("salary, pension").
        # Every option named gets its own tick; an option the user did NOT name
        # is never marked, so a blank stays blank and nothing is auto-selected.
        selected = [part.strip().lower() for part in value.split(",") if part.strip()]
        boxes = tuple(
            box
            for choice in selected
            for box in placement.option_rects.get(choice, ())
        )
        if not boxes or placement.page >= document.page_count:
            return False
        # All-or-nothing: a category box ticked without its sub-category (or the
        # reverse) is a half-stated answer, so one unusable box abandons the
        # whole option rather than leaving a misleading partial tick.
        if any(
            layout is not None and layout.is_excluded_region(placement.page, box)
            for box in boxes
        ):
            return False
        page = document[placement.page]
        # ZapfDingbats '3' is a check mark; it is a base-14 font, so this can
        # never fall back to a missing-glyph box.
        font, glyph = (
            ("zadb", "3") if placement.tick_check_mark else (_FONT, "X")
        )
        for box in boxes:
            size = min(9.0, max(5.0, box.height * 1.05))
            page.insert_text(
                fitz.Point(box.x0 + max(0.0, (box.width - size * 0.6) / 2), box.y1 - 1.5),
                glyph, fontsize=size, fontname=font, color=_INK,
            )
            occupancy[placement.page].reserve(box)
        placed.append(
            PlacedField(field_id, placement.page, PlacementSource.MANIFEST_RECT, boxes[0])
        )
        return True

    def _tick_option(
        self, document, occupancy, layout, placement: FieldPlacement,
        field_id: str, value: str, placed: list[PlacedField],
    ) -> bool:
        """
        Mark the checkbox belonging to the chosen option.

        The manifest names the printed caption for each option value; the box
        itself sits immediately to the caption's LEFT on every one of these
        forms, so the tick goes in that gap. A caption that cannot be located
        uniquely means no tick — never a tick on a guessed box.
        """
        caption = placement.option_anchors.get(value.lower())
        if not caption:
            return False
        page_no = placement.page
        if page_no >= document.page_count:
            return False
        page = document[page_no]
        hits = self._find_caption(page, caption)
        if len(hits) != 1:
            return False  # ambiguous or absent — do not guess which box
        x0, y0, x1, y1 = hits[0]
        size = min(8.0, max(5.0, y1 - y0))
        box = Rect(x0=max(1.0, x0 - size - 3.0), y0=y0, x1=x0 - 1.0, y1=y1)
        if layout is not None and layout.is_excluded_region(page_no, box):
            return False
        page.insert_text(
            fitz.Point(box.x0, y1 - 1.0),
            "X", fontsize=size, fontname=_FONT, color=_INK,
        )
        occupancy[page_no].reserve(box)
        placed.append(
            PlacedField(field_id, page_no, PlacementSource.MANIFEST_ANCHOR, box)
        )
        return True

    def _resolve_rect(
        self, document, occupancy, layout, labels, placement, field_id, value,
    ) -> tuple[int, Rect, PlacementSource] | None:
        """Find the bounded rectangle this value belongs in, or None."""
        # Explicit rectangle — verified, highest confidence for a flat form.
        if placement is not None and placement.rect is not None:
            return placement.page, placement.rect, PlacementSource.MANIFEST_RECT

        # Caption anchor named by the manifest (unambiguous by construction).
        if placement is not None and placement.anchor:
            box = self._anchor_rect(
                document, occupancy, placement.page, placement.anchor,
                placement.anchor_mode, placement.anchor_occurrence,
                placement.max_width, placement.height,
            )
            if box is not None:
                return placement.page, box, PlacementSource.MANIFEST_ANCHOR
            return None

        # A form with no text layer cannot be anchored at all.
        if layout is not None and not layout.has_text_layer:
            return None

        # Last resort: discover the caption, but only if it is UNAMBIGUOUS.
        return self._semantic_rect(document, occupancy, labels.get(field_id, ()))

    # ------------------------------------------------------------------ #
    # Caption anchoring
    # ------------------------------------------------------------------ #

    def _anchor_rect(
        self, document, occupancy, page_no: int, caption: str,
        mode: AnchorMode, occurrence: int,
        max_width: float | None, height: float | None,
    ) -> Rect | None:
        """Locate a caption on one page and derive the writable box from it."""
        if page_no >= document.page_count:
            return None
        page = document[page_no]
        hits = self._find_caption(page, caption)
        if len(hits) <= occurrence:
            return None
        return self._box_from_anchor(
            occupancy[page_no], page, hits[occurrence], mode, max_width, height
        )

    def _semantic_rect(
        self, document, occupancy, captions: tuple[str, ...]
    ) -> tuple[int, Rect, PlacementSource] | None:
        """
        Runtime caption discovery, used only when the manifest is silent.

        Requires a UNIQUE hit for a sufficiently specific caption: a caption
        appearing several times cannot identify one field, and guessing between
        them is exactly how values landed in the wrong boxes.
        """
        best: tuple[int, int, tuple] | None = None
        for caption in sorted(captions, key=len, reverse=True):
            tokens = _normalize(caption)
            # Single short tokens ("pan", "name", "date") appear all over a KYC
            # form; they can never identify a field on their own.
            if len(tokens) < 2 and (not tokens or len(tokens[0]) < 6):
                continue
            for page in document:
                hits = self._find_caption(page, caption)
                if len(hits) != 1:
                    continue  # absent, or ambiguous — either way, unusable
                score = len(caption)
                if best is None or score > best[0]:
                    best = (score, page.number, hits[0])
            if best is not None:
                break
        if best is None:
            return None
        _, page_no, anchor = best
        page = document[page_no]
        box = self._box_from_anchor(
            occupancy[page_no], page, anchor, AnchorMode.RIGHT, None, None
        )
        if box is None:
            return None
        return page_no, box, PlacementSource.SEMANTIC

    @staticmethod
    def _find_caption(page: "fitz.Page", caption: str) -> list[tuple]:
        """
        Every place `caption` is printed, as (x0, y0, x1, y1) runs.

        Tokens must match EXACTLY after normalisation. The old engine accepted
        a prefix match in either direction, which made "pa" match "pan" — the
        single loosest line in the codebase and the origin of most of the
        misplacement.
        """
        wanted = _normalize(caption)
        if not wanted:
            return []
        words = page.get_text("words") or []
        tokens = [(re.sub(r"[^a-z0-9]+", "", w[4].lower()), w) for w in words]
        hits: list[tuple] = []
        for i in range(len(tokens) - len(wanted) + 1):
            window = tokens[i : i + len(wanted)]
            if any(not tok for tok, _ in window):
                continue
            if [tok for tok, _ in window] != wanted:
                continue
            boxes = [w for _, w in window]
            if abs(boxes[0][1] - boxes[-1][1]) > 5:
                continue  # not one visual line
            hits.append(
                (
                    boxes[0][0],
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                )
            )
        return hits

    def _box_from_anchor(
        self, occupancy: _PageOccupancy, page: "fitz.Page", anchor: tuple,
        mode: AnchorMode, max_width: float | None, height: float | None,
    ) -> Rect | None:
        """Turn a located caption into a bounded, collision-checked rectangle."""
        x0, y0, x1, y1 = anchor
        # Refuse anything landing in an official-use band. Checked against the
        # text immediately around the anchor rather than the whole page, so a
        # form that merely CONTAINS a "For Bank Use Only" section elsewhere is
        # still fillable everywhere else.
        if self._in_official_band(page, y0, y1):
            return None
        page_w, page_h = page.rect.width, page.rect.height

        if mode is AnchorMode.INSIDE:
            return Rect(x0=x0, y0=y0, x1=x1, y1=y1)

        if mode is AnchorMode.BELOW:
            box_h = height or 12.0
            top = y1 + 1.5
            if top + box_h > page_h:
                return None
            width = min(max_width or 200.0, page_w - x0 - 12)
            return Rect(x0=x0, y0=top, x1=x0 + width, y1=top + box_h)

        # RIGHT: start after the caption, stop before whatever comes next.
        start = x1 + 3.0
        available = occupancy.free_width_from(start, y0, y1, page_w - 12)
        if max_width is not None:
            available = min(available, max_width)
        if available < 18.0:
            return None  # genuinely nowhere to write — skip rather than overlap
        return Rect(x0=start, y0=y0 - 0.5, x1=start + available, y1=y1 + 1.0)

    @staticmethod
    def _clear_scanned_region(page: "fitz.Page", rect: Rect) -> bool:
        """
        Erase a superseded value from a SCANNED field, keeping the form intact.

        On an image-only page the old value is pixels inside a picture, so
        there is no text object to redact. Painting the rectangle flat would
        also destroy whatever the form drew there — a comb field's cell
        dividers run straight through the middle of its own value box.

        So the clear is selective, and purely geometric (no inpainting, no
        model): dark pixels belonging to a LONG straight run are structure —
        borders, rules, comb dividers — and are preserved; every other dark
        pixel is glyph ink and is reset to the paper colour sampled from the
        region itself.

        Returns False when the result cannot be trusted, in which case the
        caller must skip rather than overprint:
          * the interior is too small to isolate from its border;
          * the region is mostly ink (a logo, a dense stamp), so "background"
            cannot be established;
          * clearing would wipe an implausible share of the region.
        """
        # Protect the printed border: never touch the outer edge of the box.
        inset = min(1.5, max(0.6, rect.height * 0.12))
        interior = rect.shrunk(inset)
        if interior.width < 4 or interior.height < 4:
            return False

        try:
            scale = 6.0
            clip = fitz.Rect(interior.x0, interior.y0, interior.x1, interior.y1)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), clip=clip, colorspace=fitz.csGRAY
            )
            width, height = pixmap.width, pixmap.height
            if width < 4 or height < 4:
                return False
            stride = pixmap.stride
            data = bytearray(pixmap.samples)

            # Paper colour: the bright majority of the region.
            bright = sorted(v for v in data if v >= 170)
            if len(bright) < (width * height) * 0.45:
                return False  # mostly ink — not a field we can safely clear
            paper = bright[len(bright) // 2]

            dark = [
                [data[y * stride + x] < 165 for x in range(width)]
                for y in range(height)
            ]
            # A structural rule spans the region EDGE TO EDGE. The bar is set
            # high deliberately: at 55% a capital letter's stem (~64% of a
            # field's height) was mistaken for a comb divider and preserved,
            # leaving ghosts of the old value under the new one.
            h_min = max(8, int(width * 0.88))
            v_min = max(8, int(height * 0.88))

            keep = [[False] * width for _ in range(height)]
            for y in range(height):
                run = 0
                for x in range(width + 1):
                    if x < width and dark[y][x]:
                        run += 1
                    else:
                        if run >= h_min:
                            for k in range(x - run, x):
                                keep[y][k] = True
                        run = 0
            for x in range(width):
                run = 0
                for y in range(height + 1):
                    if y < height and dark[y][x]:
                        run += 1
                    else:
                        if run >= v_min:
                            for k in range(y - run, y):
                                keep[k][x] = True
                        run = 0

            cleared = 0
            for y in range(height):
                row = y * stride
                for x in range(width):
                    if dark[y][x] and not keep[y][x]:
                        data[row + x] = paper
                        cleared += 1
            if cleared == 0:
                return True  # nothing to erase; the field is effectively clear
            if cleared / float(width * height) > 0.40:
                return False  # implausible: refuse rather than gut the region

            # Verify the clear actually worked before committing to it. Any
            # dark pixel left that is NOT edge-to-edge structure is a surviving
            # fragment of the old value, and drawing over that is precisely the
            # overprint this exists to prevent.
            residual = sum(
                1
                for y in range(height)
                for x in range(width)
                if dark[y][x] and keep[y][x] and not _spans_edges(keep, x, y, width, height)
            )
            if residual > (width * height) * 0.010:
                return False

            # FINAL PROOF, on the patched bytes themselves. Rasterised glyphs
            # are anti-aliased into mid-grey, so a strict "dark" mask misses
            # their edges and leaves a legible ghost. Anything still greyer
            # than paper that is not edge-to-edge structure means the clear did
            # not succeed - and drawing over a ghost is the overprint this
            # whole path exists to prevent.
            ghost = 0
            for y in range(height):
                row = y * stride
                for x in range(width):
                    if data[row + x] < paper - 25 and not _spans_edges(
                        keep, x, y, width, height
                    ):
                        ghost += 1
            if ghost > (width * height) * 0.012:
                logger.info(
                    "Scanned clear left %.1f%% residual ink; refusing to replace",
                    100.0 * ghost / (width * height),
                )
                return False

            patch = fitz.Pixmap(fitz.csGRAY, width, height, bytes(data), False)
            page.insert_image(clip, pixmap=patch, overlay=True)
        except Exception:  # noqa: BLE001 - any failure means "not safe"
            logger.exception("Scanned-region clear failed; leaving the value in place")
            return False
        return True

    @staticmethod
    def _ocr_existing_value(
        page: "fitz.Page", rect: Rect, min_confidence: float = 55.0
    ) -> str | None:
        """
        Read what is already inside a field region on an IMAGE-ONLY form.

        HDFC's PDF carries no text layer, so `_existing_value` sees nothing and
        every field looks blank — a partially-filled scan would get new values
        printed straight over the applicant's own handwriting. The region is
        rasterised at 4x and OCR'd so the same three-case logic (unchanged /
        blank / replace) applies to scans as it does to digital forms.

        Returns None when OCR is unavailable or the read is not trustworthy.
        None means "unknown", which the caller MUST treat as "do not write" —
        never as "blank".
        """
        # Ink first, and DECISIVE when it says empty. Geometry answers "is
        # anything here?" far more reliably than OCR, which happily returns
        # low-confidence noise for an empty box — and that noise, read as
        # "unknown content", made every field on a blank scan get skipped.
        # OCR is only needed to identify ink that is actually present.
        if FormPlacementEngine._looks_blank(page, rect):
            return ""
        blank = False

        try:
            import pytesseract  # noqa: PLC0415 - optional dependency
            from PIL import Image  # noqa: PLC0415

            clip = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=clip)
            image = Image.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
            # PSM 7: the region is a single text line, which is what a form
            # field is. The default page-segmentation mode assumes a whole
            # page and returns noise on a strip this small.
            data = pytesseract.image_to_data(
                image, config="--psm 7", output_type=pytesseract.Output.DICT
            )
        except Exception:  # noqa: BLE001 - OCR unavailable or failed
            # Degrade to the ink test: empty means safe to write, anything else
            # is unreadable content that must not be written over.
            logger.debug("Region OCR unavailable; falling back to the ink test")
            return "" if blank else None

        words, confidences = [], []
        for text, conf in zip(data.get("text", []), data.get("conf", [])):
            token = (text or "").strip()
            try:
                confidence = float(conf)
            except (TypeError, ValueError):
                continue
            if not token or confidence < 0:
                continue
            words.append(token)
            confidences.append(confidence)

        if not words:
            # Nothing legible. Only call that BLANK when the region really is
            # near-uniform; a smudged or low-contrast scan must stay unknown.
            return "" if blank else None

        mean = sum(confidences) / len(confidences)
        if mean < min_confidence:
            return None  # read it, but not well enough to act on
        return " ".join(words)

    @staticmethod
    def _looks_blank(page: "fitz.Page", rect: Rect) -> bool:
        """
        Is this region empty paper, ignoring the form's own printed box?

        Measured, not guessed: on the scanned HDFC form an untouched field
        region carries ~0.9% dark pixels (the comb dividers and border) while a
        filled one carries ~2.9%. The threshold sits between those, and the
        rectangle is shrunk first so the field's border contributes nothing.

        Errs deliberately LOW. Below the threshold means "definitely empty, safe
        to write"; anything above becomes "unknown", and unknown means skip. A
        busy form therefore loses placements rather than overprinting them.
        """
        try:
            inset = rect.shrunk(2.0)
            if inset.width <= 1 or inset.height <= 1:
                return False
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(4, 4),
                clip=fitz.Rect(inset.x0, inset.y0, inset.x1, inset.y1),
                colorspace=fitz.csGRAY,
            )
            samples = pixmap.samples
            sampled = range(0, len(samples), 3)
            dark = sum(1 for i in sampled if samples[i] < 160)
            return dark / max(1, len(sampled)) < 0.015
        except Exception:  # noqa: BLE001 - cannot tell => not blank => skip
            return False

    @staticmethod
    def _existing_value(page: "fitz.Page", rect: Rect) -> str:
        """
        The value already written inside this field's rectangle, if any.

        Only words whose CENTRE lies in the rectangle count, so a neighbouring
        label that merely grazes the edge is not mistaken for field content.
        Pure punctuation runs ("____", "__ __") are the blank form's own
        placeholders and are not values.
        """
        found: list[tuple[float, str]] = []
        for word in page.get_text("words") or []:
            x0, y0, x1, y1, text = word[0], word[1], word[2], word[3], word[4]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if not (rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1):
                continue
            if not re.sub(r"[\W_]+", "", text):
                continue  # placeholder rule, not a value
            found.append((x0, text))
        return " ".join(t for _, t in sorted(found))

    def _apply_redactions(
        self, document, pending: dict[int, list[Rect]],
        skipped: list[SkippedField], pending_draws: list[tuple],
    ) -> None:
        """
        Remove superseded values, keeping the form itself intact.

        Redaction is applied with line art PRESERVED, so the boxes, rules and
        borders a KYC form is made of survive while only the old text goes.
        If a page cannot be redacted safely, the fields that needed replacing
        are dropped from the draw list and reported: a form with the old value
        still legible is recoverable, one with two values overprinted is not.
        """
        for page_no, rects in pending.items():
            page = document[page_no]
            try:
                for rect in rects:
                    # A hair inside the box, so the field's own border is never
                    # clipped by the redaction.
                    page.add_redact_annot(
                        fitz.Rect(rect.x0 + 0.3, rect.y0 + 0.3,
                                  rect.x1 - 0.3, rect.y1 - 0.3)
                    )
                page.apply_redactions(
                    images=fitz.PDF_REDACT_IMAGE_NONE,
                    graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                )
            except Exception:  # noqa: BLE001 - never corrupt the output
                logger.exception("Redaction failed on page %d; skipping replacements", page_no)
                for entry in list(pending_draws):
                    if entry[0] == page_no and entry[1] in rects:
                        pending_draws.remove(entry)
                        skipped.append(SkippedField(entry[5], "replacement-unsafe"))

    def _apply_raster_clears(
        self, document, pending: dict[int, list[tuple]],
        skipped: list[SkippedField], pending_draws: list[tuple],
    ) -> None:
        """
        Erase superseded values from scanned pages before anything is drawn.

        A field whose region cannot be cleared safely is withdrawn from the
        draw list and reported `scanned-replacement-unsafe` — the applicant's
        original value stays legible, which is recoverable; two values printed
        over each other is not.
        """
        for page_no, entries in pending.items():
            page = document[page_no]
            for rect, field_id in entries:
                if self._clear_scanned_region(page, rect):
                    continue
                for entry in list(pending_draws):
                    if entry[5] == field_id and entry[0] == page_no:
                        pending_draws.remove(entry)
                skipped.append(SkippedField(field_id, "scanned-replacement-unsafe"))

    @staticmethod
    def _in_official_band(page: "fitz.Page", y0: float, y1: float) -> bool:
        """
        Is this vertical band part of a bank/branch-use section?

        Every KYC form here ends with an official block — "For Office Use
        Only" (CVL), "Branch Declaration - For Bank Use Only" (Axis), "FOR
        OFFICE USE/ATTESTATION" (SBI), "FOR BANK USE" (HDFC). Writing the
        applicant's data into those areas fabricates a bank officer's
        certification, so the whole band below such a heading is off limits.
        """
        for block in page.get_text("blocks") or []:
            if len(block) < 5:
                continue
            text = str(block[4])
            if not _OFFICIAL_USE.search(text):
                continue
            heading_top = float(block[1])
            # Everything from the heading downwards belongs to that section.
            if y1 >= heading_top - 2:
                return True
        return False

    # ------------------------------------------------------------------ #
    # Drawing
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fit_font(text: str, rect: Rect) -> float:
        """Largest font size at which `text` fits inside `rect`."""
        usable = max(1.0, rect.width - 2 * _PADDING)
        size = min(_MAX_FONT, max(_MIN_FONT, (rect.height - 2) * 0.85))
        while size > _MIN_FONT:
            if fitz.get_text_length(text, fontname=_FONT, fontsize=size) <= usable:
                return size
            size -= 0.25
        return _MIN_FONT

    def _draw_fitted(self, page: "fitz.Page", rect: Rect, value: str) -> None:
        """One line, shrunk to fit, clipped to its rectangle."""
        text = value.strip()
        size = self._fit_font(text, rect)
        usable = max(1.0, rect.width - 2 * _PADDING)
        # Even at the minimum size a very long value can exceed the box; it is
        # truncated rather than allowed to spill into the neighbouring field.
        while (
            text
            and fitz.get_text_length(text, fontname=_FONT, fontsize=size) > usable
        ):
            text = text[:-1]
        baseline = rect.y1 - max(1.5, (rect.height - size) / 2)
        page.insert_text(
            fitz.Point(rect.x0 + _PADDING, baseline),
            text, fontsize=size, fontname=_FONT, color=_INK,
        )

    def _draw_wrapped(self, page: "fitz.Page", rect: Rect, value: str) -> None:
        """Multi-line text confined to the rectangle by PyMuPDF itself."""
        box = fitz.Rect(rect.x0 + _PADDING, rect.y0, rect.x1 - _PADDING, rect.y1)
        size = _MAX_FONT
        while size >= _MIN_FONT:
            if page.insert_textbox(
                box, value.strip(), fontsize=size, fontname=_FONT,
                color=_INK, align=0,
            ) >= 0:
                return
            size -= 0.5
        # Never overflow: if it cannot be made to fit, one fitted line instead.
        self._draw_fitted(page, rect, value)

    def _draw_comb(
        self, page: "fitz.Page", rect: Rect, value: str, cells: int,
        strip: bool = True,
    ) -> None:
        """
        One character per cell, for the boxed fields KYC forms are full of
        (PAN, dates, PIN codes, account numbers).

        Drawing these as ordinary text is what made the date of birth drift
        across its boxes and collide with the field beside it.
        """
        # Separators are stripped, not just whitespace: a comb prints one
        # character per printed box, and a form showing eight date boxes means
        # DDMMYYYY. Keeping the hyphens made "01-01-1966" overflow to
        # "01-01-19" — the year silently truncated to two digits.
        text = (
            re.sub(r"[^A-Za-z0-9]", "", value.strip())
            if strip
            else re.sub(r"\s+", " ", value.strip())
        )[:cells]
        if not text:
            return
        cell_w = rect.width / cells
        size = min(_MAX_FONT, max(_MIN_FONT, min(cell_w * 1.25, rect.height * 0.8)))
        baseline = rect.y1 - max(1.5, (rect.height - size) / 2)
        for index, char in enumerate(text):
            char_w = fitz.get_text_length(char, fontname=_FONT, fontsize=size)
            centre = rect.x0 + cell_w * (index + 0.5) - char_w / 2
            page.insert_text(
                fitz.Point(centre, baseline),
                char, fontsize=size, fontname=_FONT, color=_INK,
            )

    # ------------------------------------------------------------------ #
    # Photograph + signature
    # ------------------------------------------------------------------ #

    def _place_assets(
        self, document, occupancy, widgets, layout,
        assets: dict[AssetKind, bytes],
        requirements: FormAssetRequirements | None,
        placed: list[PlacedField], skipped: list[SkippedField],
    ) -> None:
        """
        Draw the photograph and signature into validated, non-overlapping boxes.

        Order matters: the photo is resolved first and its rectangle reserved,
        so the signature can be rejected if it would land on top of it. The
        broken output had the signature box (504,189)-(565,213) sitting
        entirely INSIDE the photo box (513,157)-(587,252) — the applicant's
        signature printed across their own face.
        """
        resolved: dict[AssetKind, tuple[int, Rect]] = {}

        for kind in (AssetKind.PHOTO, AssetKind.SIGNATURE):
            if kind not in assets or not assets[kind]:
                continue
            field_id = ASSET_FIELD_IDS[kind]
            target = self._asset_rect(document, widgets, layout, requirements, kind)
            if target is None:
                skipped.append(SkippedField(field_id, "no-region"))
                continue
            page_no, rect = target

            if layout is not None and layout.is_excluded_region(page_no, rect):
                skipped.append(SkippedField(field_id, "official-use-area"))
                continue
            # The signature must never intrude on the photograph.
            photo_target = resolved.get(AssetKind.PHOTO)
            if (
                kind is AssetKind.SIGNATURE
                and photo_target is not None
                and photo_target[0] == page_no
                and rect.overlaps(photo_target[1])
            ):
                skipped.append(SkippedField(field_id, "would-overlap-photo"))
                continue

            resolved[kind] = (page_no, rect)

        for kind, (page_no, rect) in resolved.items():
            field_id = ASSET_FIELD_IDS[kind]
            drawn = self._fit_image(assets[kind], rect)
            if drawn is None:
                skipped.append(SkippedField(field_id, "undecodable"))
                continue
            try:
                document[page_no].insert_image(
                    fitz.Rect(drawn.x0, drawn.y0, drawn.x1, drawn.y1),
                    stream=assets[kind], keep_proportion=True,
                )
            except Exception:  # noqa: BLE001 - a bad image must not fail the PDF
                logger.exception("Could not draw %s", kind.value)
                skipped.append(SkippedField(field_id, "draw-failed"))
                continue
            occupancy[page_no].reserve(drawn)
            placed.append(
                PlacedField(field_id, page_no, PlacementSource.MANIFEST_RECT, drawn)
            )

    def _asset_rect(
        self, document, widgets, layout, requirements, kind: AssetKind
    ) -> tuple[int, Rect] | None:
        """Where this asset belongs: manifest first, detection second."""
        placement = None
        if layout is not None:
            placement = layout.photo if kind is AssetKind.PHOTO else layout.signature
        if placement is not None:
            if placement.widget:
                entry = widgets.get(placement.widget)
                if entry is not None:
                    page_no, _name, rect = entry
                    return page_no, rect
            if placement.rect is not None:
                return placement.page, placement.rect
            if placement.anchor:
                page = document[placement.page]
                hits = self._find_caption(page, placement.anchor)
                if len(hits) > placement.anchor_occurrence:
                    x0, y0, x1, y1 = hits[placement.anchor_occurrence]
                    if placement.anchor_mode is AnchorMode.INSIDE:
                        return placement.page, Rect(x0=x0, y0=y0, x1=x1, y1=y1)
                    box_h = placement.height or 30.0
                    return placement.page, Rect(
                        x0=x0, y0=y0 - box_h - 2, x1=x0 + (placement.max_width or 150),
                        y1=y0 - 2,
                    )
            return None

        # No manifest: fall back to runtime detection, rejecting any region
        # that sits in an official-use area of the page.
        if requirements is None:
            return None
        for region in requirements.regions(kind):
            if region.page >= document.page_count:
                continue
            rect = Rect(x0=region.x0, y0=region.y0, x1=region.x1, y1=region.y1)
            if rect.width < 8 or rect.height < 8:
                continue
            if _OFFICIAL_USE.search(region.matched_text or ""):
                continue
            return region.page, rect
        return None

    @staticmethod
    def _fit_image(image_bytes: bytes, region: Rect) -> Rect | None:
        """
        Centre an image inside its region without distortion.

        Letterboxed, not stretched: a squashed photograph looks forged and a
        stretched signature stops matching the one on file.
        """
        try:
            pixmap = fitz.Pixmap(image_bytes)
            source_w, source_h = float(pixmap.width), float(pixmap.height)
        except Exception:  # noqa: BLE001
            return None
        if source_w <= 0 or source_h <= 0:
            return None
        inner = region.shrunk(1.0)
        if inner.width <= 0 or inner.height <= 0:
            return None
        scale = min(inner.width / source_w, inner.height / source_h)
        draw_w, draw_h = source_w * scale, source_h * scale
        offset_x = inner.x0 + (inner.width - draw_w) / 2
        offset_y = inner.y0 + (inner.height - draw_h) / 2
        return Rect(
            x0=offset_x, y0=offset_y, x1=offset_x + draw_w, y1=offset_y + draw_h
        )


# Stateless singleton.
form_placement_engine = FormPlacementEngine()
