"""
FileSystemLayoutSource — load form layout manifests from backend/form_layouts/.

One JSON file per supported form, named after its document-schema id
(`cvl_kyc.json`, `icici_kyc.json`, …). Adding support for a new bank's form is
a new JSON file: no Python change, exactly like the document schemas.

Manifests are cached after first read — they are static reference data and a
generation request should not pay filesystem cost per field.
"""

import json
import logging
import threading
from pathlib import Path

from app.core.config import settings
from app.domain.form_layout import FormLayout, LayoutSource

logger = logging.getLogger(__name__)


class FileSystemLayoutSource(LayoutSource):
    """Read (and cache) form layout manifests from a directory of JSON files."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self._directory = Path(
            directory
            or getattr(settings, "FORM_LAYOUTS_DIR", "form_layouts")
        )
        self._cache: dict[str, FormLayout | None] = {}
        self._lock = threading.Lock()

    def load(self, form_id: str) -> FormLayout | None:
        """
        The manifest for `form_id`, or None when the form has none.

        None is not an error: a form with no manifest simply falls back to the
        engine's semantic strategy, which places only what it can resolve
        unambiguously.
        """
        with self._lock:
            if form_id in self._cache:
                return self._cache[form_id]

        layout = self._read(form_id)

        with self._lock:
            self._cache[form_id] = layout
        return layout

    def _read(self, form_id: str) -> FormLayout | None:
        path = self._directory / f"{form_id}.json"
        if not path.exists():
            logger.info("No layout manifest for %s (semantic fallback)", form_id)
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            layout = FormLayout.model_validate(raw)
        except Exception:  # noqa: BLE001 - a bad manifest must not break generation
            logger.exception("Invalid layout manifest at %s; ignoring", path)
            return None
        logger.info(
            "Layout manifest loaded: %s (%d field(s), text_layer=%s)",
            form_id, len(layout.fields), layout.has_text_layer,
        )
        return layout


# Shared instance — manifests are static reference data.
filesystem_layout_source = FileSystemLayoutSource()
