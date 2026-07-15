"""
In-memory adapter for the DocumentRepository port (Phase 6).

Upload METADATA lives in a plain dict keyed by document_id — same rationale as
the session and transcript stores: zero infrastructure for the hackathon MVP,
and a database adapter later only touches core/dependencies.py.

Note the asymmetry with file bytes: bytes persist on disk (LocalStorageAdapter)
while this metadata store is process-lifetime only. After a server restart the
files remain in backend/uploads/ but are no longer listed — an accepted MVP
trade-off, fixed the day a database adapter implements this same port.
"""

from app.domain.document import UploadedDocument
from app.domain.repositories import DocumentRepository
from app.core.exceptions import DuplicateDocumentError


class InMemoryDocumentRepository(DocumentRepository):
    """Dict-backed metadata store for uploaded documents."""

    def __init__(self) -> None:
        self._documents: dict[str, UploadedDocument] = {}

    def add(self, document: UploadedDocument) -> None:
        if document.document_id in self._documents:
            raise DuplicateDocumentError(document.document_id)
        self._documents[document.document_id] = document

    def get(self, document_id: str) -> UploadedDocument | None:
        return self._documents.get(document_id)

    def list_all(self) -> tuple[UploadedDocument, ...]:
        return tuple(
            sorted(
                self._documents.values(),
                key=lambda doc: doc.uploaded_at,
                reverse=True,
            )
        )

    def delete(self, document_id: str) -> bool:
        return self._documents.pop(document_id, None) is not None
