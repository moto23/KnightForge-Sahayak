"""
CoordinateMapper — turn Session.answers into a schema-free drawing plan.

Phase 8's translation layer. Loads the EXTERNAL coordinate map
(templates/kyc_coordinate_map.json — never hardcoded in Python) and reduces
every answered field to primitive Placements (text marks and checkmarks) the
PDF adapter can paint without knowing anything about the KYC schema.

Entry types supported (requirements 3 & 6):

    text      — one string at (x, y); optional char_spacing spreads the
                characters into the form's comb boxes (PAN, Aadhaar, PIN)
    choice    — option value -> its checkbox center (gender, occupation…)
    boolean   — tick a box only when the answer matches `checked_when`
    date      — dd/mm/yyyy digits distributed into 8 per-digit boxes
    multiline — long text (addresses) wrapped across the form's ruled lines

An answered field with no map entry — or a choice value with no option box —
is reported in `unmapped_fields`, never a crash: the PDF still generates and
the caller sees exactly what was left blank.
"""

import json
import logging
import re
from pathlib import Path

from app.core.exceptions import PdfTemplateCorruptError, PdfTemplateNotFoundError
from app.domain.enums import PlacementKind
from app.domain.pdf import OverlayPlan, Placement

logger = logging.getLogger(__name__)

# Values treated as "yes" for boolean checkbox fields.
_TRUTHY = {"yes", "true"}

# Rough per-character width factor for Helvetica at a given font size —
# used only for greedy line wrapping of multiline text.
_CHAR_WIDTH_FACTOR = 0.55


class CoordinateMapper:
    """Load the external coordinate map and build overlay plans from answers."""

    def __init__(self, map_path: str) -> None:
        self._map_path = Path(map_path)
        self._map = self._load(self._map_path)
        self._fields: dict = self._map["fields"]
        self._default_font: float = float(
            self._map.get("defaults", {}).get("font_size", 8.0)
        )
        logger.info(
            "Coordinate map loaded: %s v%s (%d fields)",
            self.template_id, self.template_version, len(self._fields),
        )

    # ------------------------------------------------------------------ #
    # Metadata
    # ------------------------------------------------------------------ #

    @property
    def template_id(self) -> str:
        """Id of the form this map describes."""
        return self._map["template_id"]

    @property
    def template_version(self) -> str:
        """Version of the coordinate map (recorded on every generated PDF)."""
        return self._map["template_version"]

    # ------------------------------------------------------------------ #
    # Plan building
    # ------------------------------------------------------------------ #

    def build_plan(self, answers: dict[str, str]) -> OverlayPlan:
        """
        Convert validated session answers into an OverlayPlan.

        Every entry in `answers` is already validated (Session.answers only
        holds Validation-Engine-approved values), so this method does layout
        only — no validation, no schema decisions.
        """
        placements: list[Placement] = []
        unmapped: list[str] = []

        for field_id, value in answers.items():
            value = (value or "").strip()
            if not value:
                continue
            entry = self._fields.get(field_id)
            if entry is None:
                unmapped.append(field_id)
                continue
            marks = self._place_field(field_id, value, entry)
            if marks:
                placements.extend(marks)
            else:
                unmapped.append(field_id)

        if unmapped:
            logger.warning("No coordinates for answered fields: %s", unmapped)
        return OverlayPlan(
            template_id=self.template_id,
            template_version=self.template_version,
            placements=tuple(placements),
            unmapped_fields=tuple(unmapped),
        )

    # ------------------------------------------------------------------ #
    # Per-type placement builders
    # ------------------------------------------------------------------ #

    def _place_field(self, field_id: str, value: str, entry: dict) -> list[Placement]:
        """Dispatch on the map entry's declared type."""
        kind = entry.get("type", "text")
        if kind == "text":
            return self._place_text(field_id, value, entry)
        if kind == "choice":
            return self._place_choice(field_id, value, entry)
        if kind == "boolean":
            return self._place_boolean(field_id, value, entry)
        if kind == "date":
            return self._place_date(field_id, value, entry)
        if kind == "multiline":
            return self._place_multiline(field_id, value, entry)
        logger.warning("Unknown map entry type %r for field %s", kind, field_id)
        return []

    def _place_text(self, field_id: str, value: str, entry: dict) -> list[Placement]:
        """One text mark; char_spacing > 0 spreads characters into comb boxes."""
        font_size = float(entry.get("font_size", self._default_font))
        spacing = float(entry.get("char_spacing", 0.0))
        page, x, y = int(entry["page"]), float(entry["x"]), float(entry["y"])

        if spacing <= 0:
            return [
                Placement(
                    kind=PlacementKind.TEXT,
                    page=page, x=x, y=y,
                    text=value.upper() if entry.get("uppercase", True) else value,
                    font_size=font_size,
                    max_width=entry.get("max_width"),
                    field_id=field_id,
                )
            ]
        # Comb fields (PAN, Aadhaar, PIN): one placement per character so each
        # glyph lands in its own printed box.
        step = font_size * _CHAR_WIDTH_FACTOR + spacing
        return [
            Placement(
                kind=PlacementKind.TEXT,
                page=page, x=x + i * step, y=y,
                text=ch.upper(),
                font_size=font_size,
                field_id=field_id,
            )
            for i, ch in enumerate(value.replace(" ", ""))
        ]

    def _place_choice(self, field_id: str, value: str, entry: dict) -> list[Placement]:
        """Tick the checkbox belonging to the chosen option value."""
        options: dict = entry.get("options", {})
        target = options.get(value.lower())
        if target is None:
            # Accept the human label too (session normally stores the value,
            # but be liberal: 'Male' vs 'male').
            target = next(
                (pos for key, pos in options.items() if key.lower() == value.lower()),
                None,
            )
        if target is None:
            logger.warning("No checkbox mapped for %s=%r", field_id, value)
            return []
        return [
            Placement(
                kind=PlacementKind.CHECKMARK,
                page=int(entry["page"]),
                x=float(target["x"]),
                y=float(target["y"]),
                field_id=field_id,
            )
        ]

    def _place_boolean(self, field_id: str, value: str, entry: dict) -> list[Placement]:
        """Tick the box only when the answer matches the map's checked_when."""
        checked_when = str(entry.get("checked_when", "yes")).lower()
        is_truthy = value.lower() in _TRUTHY
        should_check = (checked_when == "yes") == is_truthy
        if not should_check:
            # 'No' on this form simply leaves the box empty — still a
            # successfully handled field, so emit a zero-mark success by
            # returning a sentinel placement-free list is WRONG (would count
            # as unmapped). Emit nothing but signal success via a no-op text.
            return [
                Placement(
                    kind=PlacementKind.TEXT,
                    page=int(entry["page"]),
                    x=float(entry["x"]),
                    y=float(entry["y"]),
                    text="",  # renderer skips empty text; field counts as handled
                    field_id=field_id,
                )
            ]
        return [
            Placement(
                kind=PlacementKind.CHECKMARK,
                page=int(entry["page"]),
                x=float(entry["x"]),
                y=float(entry["y"]),
                field_id=field_id,
            )
        ]

    def _place_date(self, field_id: str, value: str, entry: dict) -> list[Placement]:
        """Distribute a date's 8 digits (ddmmyyyy) into the form's digit boxes."""
        digits = re.sub(r"\D", "", value)
        if len(digits) == 8 and value.count("-") == 2 and value.index("-") == 4:
            # ISO yyyy-mm-dd slipped through: reorder to ddmmyyyy.
            digits = digits[6:8] + digits[4:6] + digits[0:4]
        if len(digits) != 8:
            logger.warning("Date %r for %s does not have 8 digits", value, field_id)
            return []
        xs = entry["segments_x"]
        y = float(entry["y"])
        page = int(entry["page"])
        font_size = float(entry.get("font_size", self._default_font))
        return [
            Placement(
                kind=PlacementKind.TEXT,
                page=page, x=float(xs[i]), y=y,
                text=digit, font_size=font_size, field_id=field_id,
            )
            for i, digit in enumerate(digits)
        ]

    def _place_multiline(self, field_id: str, value: str, entry: dict) -> list[Placement]:
        """Greedy word-wrap long text (addresses) across the form's ruled lines."""
        font_size = float(entry.get("font_size", self._default_font))
        max_width = float(entry.get("max_width", 480.0))
        chars_per_line = max(1, int(max_width / (font_size * _CHAR_WIDTH_FACTOR)))
        lines_y: list[float] = [float(y) for y in entry["lines_y"]]
        page, x = int(entry["page"]), float(entry["x"])

        words = value.upper().split()
        lines: list[str] = [""]
        for word in words:
            candidate = f"{lines[-1]} {word}".strip()
            if len(candidate) <= chars_per_line or not lines[-1]:
                lines[-1] = candidate
            else:
                lines.append(word)
        if len(lines) > len(lines_y):
            # Too long for the ruled lines: squeeze the overflow onto the last
            # line rather than dropping it (renderer shrinks to fit max_width).
            lines = lines[: len(lines_y) - 1] + [" ".join(lines[len(lines_y) - 1:])]

        return [
            Placement(
                kind=PlacementKind.TEXT,
                page=page, x=x, y=lines_y[i],
                text=line, font_size=font_size,
                max_width=max_width, field_id=field_id,
            )
            for i, line in enumerate(lines) if line
        ]

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load(path: Path) -> dict:
        """Read + sanity-check the JSON map; typed errors for missing/corrupt."""
        if not path.exists():
            raise PdfTemplateNotFoundError(f"coordinate map not found at {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PdfTemplateCorruptError(f"coordinate map unreadable: {exc}") from exc
        for key in ("template_id", "template_version", "fields"):
            if key not in data:
                raise PdfTemplateCorruptError(f"coordinate map missing key {key!r}")
        return data
