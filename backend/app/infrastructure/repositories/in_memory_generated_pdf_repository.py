"""
In-memory GeneratedPdfRepository adapter (Phase 8).

Metadata records for generated PDFs, keyed by pdf_id — same MVP pattern as
the other in-memory stores (the PDF bytes themselves live on disk under
generated_pdfs/ and DO survive restarts; the records don't, until a database
adapter implements this same port).
"""

from app.core.exceptions import DuplicateDocumentError
from app.domain.pdf import GeneratedPdf
from app.domain.repositories import GeneratedPdfRepository


class InMemoryGeneratedPdfRepository(GeneratedPdfRepository):
    """Dict-backed store of generated-PDF metadata."""

    def __init__(self) -> None:
        self._records: dict[str, GeneratedPdf] = {}

    def add(self, record: GeneratedPdf) -> None:
        """Store a new record; refuse duplicate ids (uuid collision guard)."""
        if record.pdf_id in self._records:
            raise DuplicateDocumentError(record.pdf_id)
        self._records[record.pdf_id] = record

    def get(self, pdf_id: str) -> GeneratedPdf | None:
        """Return the record, or None if it doesn't exist."""
        return self._records.get(pdf_id)

    def list_all(self) -> tuple[GeneratedPdf, ...]:
        """Every record, newest first."""
        return tuple(
            sorted(self._records.values(), key=lambda r: r.generated_at, reverse=True)
        )

    def delete(self, pdf_id: str) -> bool:
        """Remove a record; True if it existed."""
        return self._records.pop(pdf_id, None) is not None
