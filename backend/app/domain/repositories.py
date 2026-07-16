"""
Repository ports (abstract interfaces) owned by the domain.

Services depend on THESE abstractions; concrete adapters live in
`app/infrastructure/`. Today the only adapter is an in-memory store — when
PostgreSQL arrives in a later phase, a new adapter implements this same
interface and nothing in the service layer changes (classic Repository /
Ports-and-Adapters pattern).
"""

from abc import ABC, abstractmethod

from app.domain.conversation import ConversationTurn
from app.domain.document import UploadedDocument
from app.domain.enums import DocumentCategory
from app.domain.extraction import (
    DocumentUnderstanding,
    ImageFacts,
    PdfPageFacts,
    RecognizedText,
)
from app.domain.session import Session


class SessionRepository(ABC):
    """Persistence contract for interview sessions."""

    @abstractmethod
    def add(self, session: Session) -> None:
        """Store a brand-new session."""

    @abstractmethod
    def get(self, session_id: str) -> Session | None:
        """Return the session with this id, or None if it doesn't exist."""

    @abstractmethod
    def save(self, session: Session) -> None:
        """Persist changes to an existing session (upsert semantics)."""

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """Remove a session; return True if it existed, False otherwise."""


class ConversationRepository(ABC):
    """
    Persistence contract for interview transcripts (Phase 5).

    Keyed by session id. A missing transcript is an empty tuple, never an
    error — a session that has not spoken yet simply has no turns.
    """

    @abstractmethod
    def append(self, session_id: str, turn: ConversationTurn) -> None:
        """Append one turn to a session's transcript."""

    @abstractmethod
    def history(self, session_id: str) -> tuple[ConversationTurn, ...]:
        """Return the full transcript for a session, oldest first."""

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """Drop a session's transcript; return True if one existed."""


class DocumentRepository(ABC):
    """
    Persistence contract for uploaded-document METADATA (Phase 6).

    Metadata only — file bytes are the FileStorage port's job. Keeping the two
    ports separate means a database can later own metadata while S3 owns bytes,
    without either knowing about the other.
    """

    @abstractmethod
    def add(self, document: UploadedDocument) -> None:
        """Store a new document record. Raises on duplicate document_id."""

    @abstractmethod
    def get(self, document_id: str) -> UploadedDocument | None:
        """Return the record with this id, or None if it doesn't exist."""

    @abstractmethod
    def list_all(self) -> tuple[UploadedDocument, ...]:
        """Return every stored record, newest upload first."""

    @abstractmethod
    def delete(self, document_id: str) -> bool:
        """Remove a record; return True if it existed, False otherwise."""


class FileStorage(ABC):
    """
    Storage contract for uploaded-file BYTES (Phase 6).

    The upload pipeline only ever talks to this interface; today's adapter is
    LocalStorageAdapter (backend/uploads/), and an S3 adapter later implements
    these same four methods — nothing in the service layer changes.
    """

    @abstractmethod
    def save(self, category: DocumentCategory, stored_filename: str, content: bytes) -> str:
        """Persist file bytes; return the storage location (path/URI) for logs."""

    @abstractmethod
    def read(self, category: DocumentCategory, stored_filename: str) -> bytes:
        """Return the stored bytes. Raises FileNotFoundError if absent."""

    @abstractmethod
    def delete(self, category: DocumentCategory, stored_filename: str) -> bool:
        """Remove the stored file; return True if it existed."""

    @abstractmethod
    def exists(self, category: DocumentCategory, stored_filename: str) -> bool:
        """True if the file is present in storage."""


class OCRProvider(ABC):
    """
    Recognition contract for turning IMAGE BYTES into text (Phase 7).

    This port is the ONLY thing the application knows about OCR. The concrete
    engine (Tesseract today; a cloud OCR API, PaddleOCR, or a vision LLM
    tomorrow) lives in `app/infrastructure/ocr/` and is bound exactly once in
    the composition root — no module outside that adapter may import
    pytesseract or shell out to a tesseract binary.
    """

    @abstractmethod
    def recognize(self, image_bytes: bytes) -> RecognizedText:
        """
        Recognize the text in one image (PNG/JPEG bytes).

        Must handle rotated input (auto-detect orientation where the engine
        supports it) and must NOT raise for a blank/unreadable image — return
        empty text with zero confidence instead. Raises OCRFailedError only
        when the engine itself is broken/unavailable.
        """

    @abstractmethod
    def engine_name(self) -> str:
        """Human-readable engine identifier for logs/metadata (e.g. 'tesseract 5.4')."""


class DocumentInspector(ABC):
    """
    Low-level document introspection contract (Phase 7).

    Everything that requires a PDF or imaging library (page counts, text
    layers, rasterization, pixel statistics) sits behind this port, so PyMuPDF
    and Pillow stay confined to `app/infrastructure/` exactly like Tesseract.
    The DocumentAnalysisService consumes the raw facts and applies judgement.
    """

    @abstractmethod
    def pdf_page_facts(self, pdf_bytes: bytes) -> tuple[PdfPageFacts, ...]:
        """Structural facts per PDF page. Raises DocumentUnreadableError-worthy ValueError on corrupt PDFs."""

    @abstractmethod
    def pdf_page_text(self, pdf_bytes: bytes, page_number: int) -> str:
        """The embedded text layer of one page (may be empty)."""

    @abstractmethod
    def render_pdf_page(self, pdf_bytes: bytes, page_number: int, dpi: int) -> bytes:
        """Rasterize one PDF page to PNG bytes at the given DPI (for OCR)."""

    @abstractmethod
    def image_facts(self, image_bytes: bytes) -> ImageFacts:
        """Pixel statistics of an image. Raises ValueError on undecodable bytes."""


class DocumentUnderstandingRepository(ABC):
    """
    Persistence contract for cached pipeline results (Phase 7).

    OCR is the most expensive step in the backend, so once a document has been
    understood, the full DocumentUnderstanding record is cached here keyed by
    document_id. Re-running the pipeline is idempotent; deleting the document
    should drop the record too.
    """

    @abstractmethod
    def save(self, record: DocumentUnderstanding) -> None:
        """Store (or replace) the pipeline result for a document."""

    @abstractmethod
    def get(self, document_id: str) -> DocumentUnderstanding | None:
        """Return the cached result, or None if the document was never processed."""

    @abstractmethod
    def delete(self, document_id: str) -> bool:
        """Drop a cached result; return True if one existed."""
