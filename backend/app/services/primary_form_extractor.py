"""
PrimaryFormExtractor — read a KYC form's OWN filled-in values, precisely.

WHY THIS EXISTS
---------------
Label-anchored extraction asks "what text follows this caption?". On a document
that is mostly captions — which is exactly what a blank KYC form is — the answer
is another caption. Every one of the five supported templates produced
applicant data from its own printed furniture:

    SBI    address = "A-PASSPORT"          (an unselected POI option)
    HDFC   address = "& CONTACT"           (half of a section heading)
           state   = "93317/06.04.2026 M253" (the printer's plate code)
    ICICI  name    = "Prefix"              (a placeholder hint)
           state   = "Premise"             (the next field's caption)
    Axis   name    = "Proof"               (part of "Name as per ID Proof")
           father  = "Or"                  (a connector word)
           address = "I N D I A"           (pre-printed country boxes)
    CVL/all gender = "male", nationality = "indian"
                                           (option words that are merely PRINTED)

Those reached the Canonical Profile, counted as prefilled, and would have been
printed onto the applicant's form as fact.

THE FIX
-------
Stop searching the page. A value is read ONLY from the rectangle the form's
manifest says that field occupies — the same measured geometry the placement
engine writes into. Text outside a field's own box is, by definition, not that
field's value.

Choice fields are handled separately and strictly: an option counts as chosen
only when its tick box carries ink. The word "Male" being printed on a form has
never meant the applicant is male.

Precision is the explicit priority. A field this returns nothing for is simply
asked in the interview, which is safe; a wrong value entering the profile is
not.
"""

import logging
import re

from app.domain.canonical_schema import CanonicalSchemaRegistry, canonical_registry
from app.domain.enums import ExtractionMethod, ExtractionSource
from app.domain.form_layout import FormLayout, PlacementMode, Rect
from app.domain.intelligence import CanonicalValue
from app.infrastructure.pdf.form_placement_engine import FormPlacementEngine

logger = logging.getLogger(__name__)

try:  # PyMuPDF is already a hard dependency of the PDF layer.
    import fitz
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]

# Values that are never applicant data however they were read: a lone
# connector, a pre-printed country, a plate/revision code. Kept deliberately
# tiny — the region restriction does the real work, this only catches text
# printed INSIDE a field's own box.
_NEVER_A_VALUE = re.compile(
    r"^(or|and|to|the|n\s*a|nil|none|same|prefix|premise|proof)$"
    r"|^\d{4,}[/\-.]\d",
    re.I,
)

# Hint text these forms print INSIDE the value box to show what belongs there.
# It sits in the field's own rectangle, so geometry alone cannot exclude it.
_PLACEHOLDER_PHRASES = frozenset({
    "first name", "middle name", "last name", "full name", "surname",
    "prefix", "suffix", "title", "premise", "bldg name", "road name",
    "dd mm yyyy", "ddmmyyyy", "d d m m y y y y", "yyyy", "mm", "dd",
    "or form 60", "form 60", "std", "isd", "number", "extension number",
    "please specify", "if any", "if applicable", "same as id proof",
})


# What a comb field's printed hint spells once the cell spacing is removed.
_COMB_HINTS = (
    "ddmmyyyy", "ddmmyy", "yyyy", "firstname", "middlename", "lastname",
    "surname", "number", "india", "prefix", "std", "isd",
)


def _is_placeholder(text: str) -> bool:
    """
    Is this the form's printed hint rather than something a person wrote?

    Two signals, both general rather than tuned to one template:

      * a run of single characters — "D D M M Y Y Y Y", "F I R S T N A M E" —
        which is how every one of these forms labels a comb field. Nobody
        writes their name one spaced letter at a time;
      * a known hint phrase printed inside the box ("First Name", "Or Form 60").
    """
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()
    if not normalized:
        return True
    if normalized in _PLACEHOLDER_PHRASES:
        return True
    tokens = normalized.split()
    # A comb field reads back as spaced single characters whether it holds a
    # hint ("D D M M Y Y Y Y") or a real answer ("A N J A L I R A O"), so the
    # spacing alone proves nothing. Join it up and judge the actual word:
    # rejecting every spaced run also threw away genuinely filled comb fields.
    if len(tokens) >= 3 and all(len(t) == 1 for t in tokens):
        joined = "".join(tokens)
        return any(hint in joined for hint in _COMB_HINTS)
    # A lone digit or letter left over from a pre-printed prefix ("+91" -> "1").
    if len(normalized) <= 2 and not normalized.isdigit():
        return True
    if len(tokens) == 1 and len(normalized) <= 2:
        return True
    return False


# A tick box is small and mostly border, so the whole-rectangle ink test used
# for comb fields reports every one of them as "not blank". Only the INTERIOR
# is examined here, and it must be clearly marked - a faint scan artefact is
# not a selection.
_CHECKBOX_INSET = 0.35
# A real tick fills a good part of the box interior. Unmarked boxes on the
# supported templates measure 0.00-0.15 at this inset (the derived rectangles
# clip a little of the printed border), so the floor sits above that.
_CHECKBOX_MARKED_RATIO = 0.18
# ...and the winner must also stand out from its siblings. On a blank form
# every option reads the same, so nothing is selected; on a filled one the
# ticked box is markedly darker than the rest.
_CHECKBOX_DOMINANCE = 2.0

# Confidence for a value read out of its own verified rectangle. High: the
# geometry was measured against this exact form, so the only uncertainty left
# is the character recognition itself.
_REGION_CONFIDENCE = 0.94


class PrimaryFormExtractor:
    """Extract applicant values from a primary KYC form's own field regions."""

    def __init__(self, canonical: CanonicalSchemaRegistry = canonical_registry) -> None:
        self._canonical = canonical
        self._engine = FormPlacementEngine()

    def supports(self, layout: FormLayout | None) -> bool:
        """True when this form has the measured geometry the method needs."""
        return fitz is not None and layout is not None and bool(layout.fields)

    def extract(
        self, pdf_bytes: bytes, layout: FormLayout, document_id: str
    ) -> tuple[CanonicalValue, ...]:
        """
        Read every mapped field from its own rectangle/widget.

        Returns only values that are genuinely present. Never raises for
        content problems — an unreadable form yields nothing, which the
        interview then collects normally.
        """
        field_to_canonical = self._inverse_map()
        values: list[CanonicalValue] = []

        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            widgets = self._engine._index_widgets(document, layout)
            for field_id, placement in layout.fields.items():
                canonical_id = field_to_canonical.get(field_id)
                if canonical_id is None:
                    continue  # form-specific field with no canonical home
                if placement.page >= document.page_count:
                    continue
                page = document[placement.page]

                if placement.mode is PlacementMode.CHECK:
                    raw = self._read_choice(page, widgets, placement)
                elif placement.widget:
                    raw = self._read_widget(page, widgets, placement)
                elif placement.rect is not None:
                    raw = self._read_region(page, placement.rect, layout)
                else:
                    raw = None  # anchor-only: no verified box, so no read

                if not raw:
                    continue
                cleaned = re.sub(r"\s+", " ", raw).strip()
                if not cleaned or _NEVER_A_VALUE.match(cleaned) or _is_placeholder(cleaned):
                    logger.debug("Rejected %r in %s as non-value", cleaned, field_id)
                    continue
                values.append(
                    CanonicalValue(
                        canonical_id=canonical_id,
                        value=cleaned,
                        confidence=_REGION_CONFIDENCE,
                        # Validation is applied downstream by the existing
                        # engine, exactly as for every other extraction path.
                        valid=True,
                        validation_message="read from the form's own field region",
                        method=ExtractionMethod.LABEL,
                        source=ExtractionSource.PDF_TEXT_LAYER,
                        page_number=placement.page + 1,
                        document_id=document_id,
                    )
                )
        finally:
            document.close()

        logger.info(
            "Primary-form region extraction (%s): %d value(s) from %d mapped field(s)",
            layout.form_id, len(values), len(layout.fields),
        )
        return tuple(values)

    # ------------------------------------------------------------------ #
    # Readers
    # ------------------------------------------------------------------ #

    def _read_widget(self, page, widgets, placement) -> str | None:
        """An AcroForm value is authoritative - the author defined the box."""
        entry = widgets.get(placement.widget)
        if entry is None:
            return None
        _page_no, field_name, _rect = entry
        try:
            for widget in page.widgets() or []:
                if (widget.field_name or "") == field_name:
                    return (str(widget.field_value or "") or None)
        except Exception:  # noqa: BLE001 - unreadable widget: treat as empty
            return None
        return None

    def _read_region(
        self, page, rect: Rect, layout: FormLayout
    ) -> str | None:
        """
        Text inside this field's own box, or None when nothing legible is there.

        On an image-only form the region OCR/ink logic already built for safe
        replacement is reused: "uncertain" returns None, so a scan never
        guesses.
        """
        existing = self._engine._existing_value(page, rect)
        if existing:
            return existing
        if not layout.has_text_layer:
            read = self._engine._ocr_existing_value(page, rect)
            return read or None
        return None

    def _read_choice(self, page, widgets, placement) -> str | None:
        """
        The selected option, or None when nothing is actually marked.

        This is the rule that stops a form's printed option words becoming
        answers. "Male", "Indian", "Married", "Student" appear on every blank
        template; none of them is a selection until its box carries ink.
        """
        for value, widget_name in placement.option_widgets.items():
            entry = widgets.get(widget_name)
            if entry is None:
                continue
            # A checkbox widget reports its own on/off state.
            live = self._live_checkbox(page, entry)
            if live:
                return value

        # Judged together, not one at a time: "which of these is marked?" is
        # answerable even when the boxes are slightly misaligned, whereas
        # "is this one marked?" is not.
        # The LAST box of an option is the discriminating one. Where a form
        # records an answer as a category plus a sub-category ("S-Service" then
        # "Private Sector"), the category box is shared by several options, so
        # measuring it would score them identically; the sub-category box is
        # what tells them apart. For a single-box option the two are the same.
        inked = {v: self._ink(page, boxes[-1])
                 for v, boxes in placement.option_rects.items() if boxes}
        inked = {v: r for v, r in inked.items() if r >= 0}
        if inked:
            best = max(inked, key=lambda v: inked[v])
            top = inked[best]
            rest = sorted((r for v, r in inked.items() if v != best), reverse=True)
            runner_up = rest[0] if rest else 0.0
            if top >= _CHECKBOX_MARKED_RATIO and (
                runner_up == 0.0 or top >= runner_up * _CHECKBOX_DOMINANCE
            ):
                return best

        # option_anchors have no measured box, so "is it ticked?" cannot be
        # answered. Silence is the correct answer.
        return None

    @staticmethod
    def _ink(page, box: Rect) -> float:
        """
        Fraction of the box INTERIOR that carries ink, or -1 if unmeasurable.

        Only the interior counts. Measuring the whole rectangle counted the
        printed border and reported every option on every blank form as
        selected - which is how "Male", "Indian" and "Retired" became applicant
        answers on templates nobody had touched.
        """
        try:
            inset_x = box.width * _CHECKBOX_INSET
            inset_y = box.height * _CHECKBOX_INSET
            interior = Rect(x0=box.x0 + inset_x, y0=box.y0 + inset_y,
                            x1=box.x1 - inset_x, y1=box.y1 - inset_y)
            if interior.width <= 0.5 or interior.height <= 0.5:
                return -1.0
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(6, 6),
                clip=fitz.Rect(interior.x0, interior.y0, interior.x1, interior.y1),
                colorspace=fitz.csGRAY,
            )
            samples = pixmap.samples
            if not samples:
                return -1.0
            dark = sum(1 for i in range(len(samples)) if samples[i] < 150)
            return dark / len(samples)
        except Exception:  # noqa: BLE001 - cannot tell => not selected
            return -1.0

    @staticmethod
    def _live_checkbox(page, entry) -> bool:
        """Is this AcroForm checkbox actually on?"""
        _page_no, field_name, _rect = entry
        try:
            for widget in page.widgets() or []:
                if (widget.field_name or "") == field_name:
                    return bool(widget.field_value) and str(
                        widget.field_value
                    ).lower() not in {"off", "false", "no", ""}
        except Exception:  # noqa: BLE001
            return False
        return False

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _inverse_map(self) -> dict[str, str]:
        """interview field id -> canonical id (the registry maps the other way)."""
        mapping: dict[str, str] = {}
        for canonical in self._canonical.all_fields():
            field = self._canonical.session_field(canonical.id)
            if field is not None:
                mapping.setdefault(field.id, canonical.id)
        return mapping


primary_form_extractor = PrimaryFormExtractor()
