"""
FileSystemSchemaSource — loads document schemas from backend/schemas/*.json.

The SchemaSource adapter: every supported form/document type lives as one
JSON file (cvl.json, sbi.json, pan.json, …) validated against the typed
DocumentSchema model on load. Adding support for a new bank's KYC form is a
new JSON file in this directory — zero Python changes, exactly the Phase 11
"schema-driven, never hardcoded" rule.

A malformed file is skipped with a warning (one bad schema must not take the
whole pipeline down); files are cached after the first load and refreshed
automatically when anything in the directory changes on disk.
"""

import json
import logging
from pathlib import Path
from threading import Lock

from pydantic import ValidationError

from app.core.config import Settings, settings
from app.domain.intelligence import DocumentSchema, SchemaSource

logger = logging.getLogger(__name__)


class FileSystemSchemaSource(SchemaSource):
    """Load (and cache) DocumentSchema definitions from a directory of JSON files."""

    def __init__(self, config: Settings = settings) -> None:
        self._directory = Path(config.DOCUMENT_SCHEMAS_DIR)
        self._lock = Lock()
        self._cache: tuple[DocumentSchema, ...] | None = None
        self._cache_stamp: tuple[tuple[str, float], ...] | None = None

    def load_all(self) -> tuple[DocumentSchema, ...]:
        """Every valid schema, alphabetical by filename (stable order)."""
        stamp = self._directory_stamp()
        with self._lock:
            if self._cache is not None and stamp == self._cache_stamp:
                return self._cache
            schemas = self._read_schemas()
            self._cache = schemas
            self._cache_stamp = stamp
            return schemas

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _directory_stamp(self) -> tuple[tuple[str, float], ...]:
        """(name, mtime) of every JSON file — cheap change detection."""
        if not self._directory.is_dir():
            return ()
        return tuple(
            sorted(
                (path.name, path.stat().st_mtime)
                for path in self._directory.glob("*.json")
            )
        )

    def _read_schemas(self) -> tuple[DocumentSchema, ...]:
        schemas: list[DocumentSchema] = []
        seen_ids: set[str] = set()
        if not self._directory.is_dir():
            logger.warning("Schema directory %s does not exist", self._directory)
            return ()
        for path in sorted(self._directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                schema = DocumentSchema.model_validate(data)
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                logger.warning("Skipping invalid document schema %s: %s", path.name, exc)
                continue
            if schema.id in seen_ids:
                logger.warning(
                    "Skipping %s: duplicate schema id %r", path.name, schema.id
                )
                continue
            seen_ids.add(schema.id)
            schemas.append(schema)
        logger.info(
            "Loaded %d document schemas from %s: %s",
            len(schemas),
            self._directory,
            ", ".join(s.id for s in schemas) or "(none)",
        )
        return tuple(schemas)
