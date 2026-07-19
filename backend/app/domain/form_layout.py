"""
Form layout manifests — where each field actually goes on a specific form.

WHY THIS EXISTS
---------------
The previous engine had exactly one strategy for flat forms: find a printed
caption, then draw the value to the right of it with only the page edge as a
bound. That produced the corrupted output this module was written to fix:

  * an unrelated value in a field, because caption matching was fuzzy enough
    that the page token "p.a." matched the caption "pan";
  * two values overlapping on one baseline ("12-03-2009876823678"), because
    nothing tracked what had already been drawn;
  * text running through neighbouring boxes, because "budget" was the distance
    to the page margin rather than the width of the field;
  * a signature stamped across the applicant's photograph, because every
    caption containing "sign" was treated as a signature target.

The fix is not more coordinates — it is a placement CONTRACT. A manifest states,
per form, exactly where a field lives and how it is drawn, and the engine
refuses to place anything it cannot resolve to a bounded rectangle.

PLACEMENT PRIORITY (highest first)
----------------------------------
  1. ACROFORM  — a named widget. The form's author defined the box; nothing
                 beats it. Used by ICICI (133 widgets).
  2. MANIFEST  — a verified rectangle or caption anchor recorded here, for
                 forms with no widgets (CVL, SBI, Axis) or no text layer at
                 all (HDFC is pure vector/scan: zero extractable text).
  3. SEMANTIC  — caption anchor discovered at runtime, but only with an
                 UNAMBIGUOUS match and a bounded target rectangle.
  4. (nothing) — if none of the above resolves, the field is SKIPPED and
                 reported. A blank a human can fill beats a wrong value they
                 might not notice.

Pure data + geometry. No I/O, no PDF library, no framework.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlacementSource(str, Enum):
    """How a field's target rectangle was resolved (for logs and reporting)."""

    ACROFORM = "acroform"
    MANIFEST_RECT = "manifest_rect"
    MANIFEST_ANCHOR = "manifest_anchor"
    SEMANTIC = "semantic"


class PlacementMode(str, Enum):
    """How a value is rendered inside its rectangle."""

    TEXT = "text"          # a single line, shrunk to fit
    MULTILINE = "multiline"  # wrapped across the rectangle
    COMB = "comb"          # one character per cell (PAN, DOB, PIN, account no.)
    CHECK = "check"        # tick a box
    IMAGE = "image"        # photograph / signature


class AnchorMode(str, Enum):
    """Where the writable box sits relative to a located caption."""

    RIGHT = "right"  # to the right of the caption, on its baseline
    BELOW = "below"  # directly beneath the caption
    INSIDE = "inside"  # the caption's own block IS the box (photo boxes)


class Rect(BaseModel):
    """An axis-aligned rectangle in PDF points, top-left origin."""

    model_config = ConfigDict(frozen=True)

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def overlaps(self, other: "Rect", tolerance: float = 0.5) -> bool:
        """
        True when two rectangles share more than a hair of space.

        `tolerance` lets boxes that merely touch (a comb cell against its
        neighbour) pass, while genuine overlap — the signature landing on the
        photograph — is caught.
        """
        return not (
            self.x1 - tolerance <= other.x0
            or other.x1 - tolerance <= self.x0
            or self.y1 - tolerance <= other.y0
            or other.y1 - tolerance <= self.y0
        )

    def shrunk(self, padding: float) -> "Rect":
        return Rect(
            x0=self.x0 + padding,
            y0=self.y0 + padding,
            x1=self.x1 - padding,
            y1=self.y1 - padding,
        )


class NameSegments(BaseModel):
    """
    The first / middle / last boxes of a form that splits a person's NAME.

    Central-KYC forms (the new ICICI form) do not print one name line: they
    print four labelled column groups — Prefix, First Name, Middle Name, Last
    Name — each its own run of character cells. Our canonical model holds one
    `full_name` string, so it has to be divided the way a human filling the
    form divides it, or the value lands in the wrong columns.

    Treating the whole row as a single wide comb was rejected: the groups are
    separated by a one-cell gutter, so "RAJUBHAI SAHEBLAL PATEL" would read as
    First = "RAJUBHAI SAH", Middle = "EBLAL PATEL", Last = "" — three wrong
    facts on a KYC form rather than one long one.

    Prefix is deliberately absent: Mr/Mrs/Ms is not something we hold, and
    guessing one from a name would be an invented (and gendered) claim.
    """

    model_config = ConfigDict(frozen=True)

    first: Rect
    middle: Rect
    last: Rect
    cells: int = Field(
        ..., gt=0, description="Character cells per box (equal on these forms)."
    )


class LayoutGuard(BaseModel):
    """
    A structural landmark that must be where the manifest says before ANY
    value is written to the form.

    Measured rectangles are only as trustworthy as the assumption that the
    uploaded file really is the template they were measured against. Usually a
    wrong assumption is merely untidy. On the Axis CK001 form it is not: that
    form repeats an IDENTICAL applicant block four times (Primary, then three
    Joint), and the only thing separating the Primary block from the 1st Joint
    block is a y coordinate. A copy paginated even slightly differently would
    put our Primary-block rectangles on top of a JOINT applicant's row — one
    person's details filed as another's, on a page that would look plausible.

    So the manifest can name a printed heading and the band its top must fall
    in. If the heading is missing or has moved, the form is not the layout we
    measured, and nothing is placed at all.
    """

    model_config = ConfigDict(frozen=True)

    anchor: str = Field(..., description="Printed heading to locate at runtime.")
    page: int = Field(default=0, ge=0)
    occurrence: int = Field(
        default=0, ge=0, description="Which occurrence to check when repeated."
    )
    min_y: float = Field(..., description="Lowest acceptable top edge, in points.")
    max_y: float = Field(..., description="Highest acceptable top edge, in points.")


class FieldPlacement(BaseModel):
    """Where ONE interview field goes on ONE form."""

    model_config = ConfigDict(frozen=True)

    page: int = Field(default=0, ge=0, description="0-based page index.")
    mode: PlacementMode = Field(default=PlacementMode.TEXT)

    widget: str | None = Field(
        default=None,
        description=(
            "Exact AcroForm field name (last dotted segment). Matched "
            "EXACTLY — never by substring, which is what let 'name' collide "
            "with every one of ICICI's six *_name widgets."
        ),
    )
    rect: Rect | None = Field(
        default=None, description="Verified rectangle, for forms with no widgets."
    )
    anchor: str | None = Field(
        default=None, description="Printed caption to locate at runtime."
    )
    anchor_mode: AnchorMode = Field(default=AnchorMode.RIGHT)
    anchor_occurrence: int = Field(
        default=0,
        ge=0,
        description=(
            "Which occurrence of the caption to use when a form prints it more "
            "than once (Axis prints 'Address' for both communication and "
            "permanent address). 0 = first."
        ),
    )
    max_width: float | None = Field(
        default=None, description="Hard cap on the writable width in points."
    )
    height: float | None = Field(
        default=None, description="Box height for anchor-derived rectangles."
    )
    cells: int | None = Field(
        default=None, description="Number of character cells for COMB mode."
    )
    date_format: str | None = Field(
        default=None,
        description=(
            "COMB mode: re-render a date to this layout before laying it out, "
            "using the tokens DD, MM, YY and YYYY (e.g. 'DDMMYY'). Needed where "
            "a form gives a date fewer cells than DD-MM-YYYY needs: HDFC prints "
            "SIX boxes, so '19-07-2026' was truncated to '190720' - the year "
            "silently became 2020. OPT-IN: a field without it keeps the plain "
            "strip-and-fill behaviour every other form relies on."
        ),
    )
    strip_separators: bool = Field(
        default=True,
        description=(
            "COMB mode: drop non-alphanumeric characters before laying the "
            "value out. Correct for dates and PANs, where a form prints eight "
            "boxes meaning DDMMYYYY. MUST be false for an email or an address, "
            "where '@' and '.' are part of the value — stripping them turned "
            "'a.b@example.com' into 'abexamplecom'."
        ),
    )
    option_widgets: dict[str, str] = Field(
        default_factory=dict,
        description="Choice value -> exact widget name, for CHECK mode.",
    )
    option_anchors: dict[str, str] = Field(
        default_factory=dict,
        description="Choice value -> printed caption to tick beside.",
    )
    option_text: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Choice value -> the exact text to write when the form captures a "
            "choice as free text rather than tick boxes. Needed where the "
            "form's cell cannot hold the option's label: HDFC records gender in "
            "a single M/F/T box, so 'male' must render as 'M', not 'Male'. "
            "Falls back to the option label when a value is not listed."
        ),
    )
    option_rects: dict[str, tuple[Rect, ...]] = Field(
        default_factory=dict,
        description=(
            "Choice value -> the tick box(es) to mark, measured. Required for a "
            "form with no text layer (HDFC is a scan), where there is no "
            "caption to anchor against and a runtime guess is impossible.\n\n"
            "A value may name SEVERAL boxes because some forms record one "
            "answer as a category plus a sub-category: the Central-KYC form "
            "prints 'S-Service ( Private Sector / Public Sector / Government "
            "Sector )', and ticking the sub-box alone omits the S code the "
            "registry actually files the occupation under. A manifest may "
            "write one rectangle or a list; a single one is read as a list of "
            "one, so every existing manifest keeps its exact behaviour."
        ),
    )

    @field_validator("option_rects", mode="before")
    @classmethod
    def _accept_single_rect(cls, value: Any) -> Any:
        """Let a manifest write one rectangle where a list is allowed."""
        if not isinstance(value, dict):
            return value
        return {
            key: (boxes if isinstance(boxes, (list, tuple)) else [boxes])
            for key, boxes in value.items()
        }

    tick_check_mark: bool = Field(
        default=False,
        description=(
            "Mark chosen options with a check mark instead of the default X. "
            "For a form that prints its options as bare words with no boxes "
            "(SBI's 'Sources of Funds' row), where a tick reads as a selection "
            "and an X can read as a deletion. Drawn in ZapfDingbats, which is "
            "a base-14 PDF font, so no glyph can go missing."
        ),
    )
    name_segments: NameSegments | None = Field(
        default=None,
        description=(
            "Split this value across First / Middle / Last name boxes instead "
            "of writing it into one rectangle. See NameSegments."
        ),
    )


class FormLayout(BaseModel):
    """The complete placement contract for one KYC form."""

    model_config = ConfigDict(frozen=True)

    form_id: str = Field(..., description="Document schema id (e.g. 'icici_kyc').")
    label: str = Field(default="", description="Human-readable form name.")
    has_text_layer: bool = Field(
        default=True,
        description=(
            "False when the PDF is pure vector/scan with no extractable text "
            "(HDFC). Caption anchoring is impossible on such a form, so only "
            "explicit rectangles and widgets can be used."
        ),
    )
    fields: dict[str, FieldPlacement] = Field(
        default_factory=dict, description="Interview field id -> placement."
    )
    photo: FieldPlacement | None = Field(
        default=None, description="Where the applicant photograph belongs."
    )
    signature: FieldPlacement | None = Field(
        default=None, description="Where the APPLICANT's signature belongs."
    )
    not_on_form: tuple[str, ...] = Field(
        default=(),
        description=(
            "Canonical fields this form genuinely does NOT have, verified "
            "against the real PDF. Recorded so a skip can say 'not-on-form' "
            "rather than 'unmapped' - the two mean very different things when "
            "judging coverage, and conflating them made four forms look far "
            "less complete than they are."
        ),
    )
    excluded_widget_patterns: tuple[str, ...] = Field(
        default=(),
        description=(
            "Substrings marking widgets that must NEVER be written to: branch "
            "use, employee/official signatures, acknowledgement stubs. Filling "
            "these would forge a bank officer's certification."
        ),
    )
    excluded_regions: tuple[tuple[int, Rect], ...] = Field(
        default=(),
        description="(page, rect) areas no value may be drawn into.",
    )
    layout_guards: tuple[LayoutGuard, ...] = Field(
        default=(),
        description=(
            "Landmarks proving the upload really is this layout before "
            "anything is written. Empty for every form whose sections cannot "
            "be confused with one another, which is all of them except Axis "
            "CK001 - see LayoutGuard."
        ),
    )

    def is_excluded_widget(self, widget_name: str) -> bool:
        """True when a widget belongs to an official-use-only section."""
        lowered = widget_name.lower()
        return any(pattern in lowered for pattern in self.excluded_widget_patterns)

    def is_excluded_region(self, page: int, rect: Rect) -> bool:
        """True when a rectangle intrudes on an official-use area."""
        return any(
            page == excluded_page and rect.overlaps(excluded)
            for excluded_page, excluded in self.excluded_regions
        )


class LayoutSource:
    """
    Port for loading form layouts. Concrete adapter reads JSON from
    backend/form_layouts/ — services never touch the filesystem themselves.
    """

    def load(self, form_id: str) -> FormLayout | None:  # pragma: no cover - interface
        raise NotImplementedError
