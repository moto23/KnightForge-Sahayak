"""
In-memory DocumentUnderstandingRepository adapter (Phase 7).

Caches each document's full pipeline result (analysis + raw OCR + extraction)
keyed by document_id, so GET /ocr/{document_id} and POST /ocr/prefill never
pay the OCR cost twice. Same MVP trade-off as the other in-memory stores:
results vanish on restart; a database adapter later implements the identical
port with zero service changes.
"""

from app.domain.extraction import DocumentUnderstanding
from app.domain.repositories import DocumentUnderstandingRepository


class InMemoryDocumentUnderstandingRepository(DocumentUnderstandingRepository):
    """Dict-backed cache of pipeline results, keyed by document_id."""

    def __init__(self) -> None:
        self._records: dict[str, DocumentUnderstanding] = {}

    def save(self, record: DocumentUnderstanding) -> None:
        """Store or replace the result for a document (re-processing is idempotent)."""
        self._records[record.document_id] = record

    def get(self, document_id: str) -> DocumentUnderstanding | None:
        """Return the cached result, or None if never processed."""
        return self._records.get(document_id)

    def delete(self, document_id: str) -> bool:
        """Drop the cached result; True if one existed."""
        return self._records.pop(document_id, None) is not None
