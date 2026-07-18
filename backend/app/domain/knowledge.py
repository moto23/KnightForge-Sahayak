"""
Knowledge RAG domain (Phase 10) — models and ports for the knowledge engine.

Everything the knowledge module IS, expressed without any library names:
chunks of official KYC documents, retrieval results with similarity scores,
a grounded answer with citations, and the ports the service depends on
(embedding provider, vector store, corpus loader). Concrete adapters —
SentenceTransformers, ChromaDB, the filesystem loader — live in
`app/infrastructure/knowledge/` and are bound once in the composition root,
exactly like OCR and PDF generation before it.

Deliberately independent of every other domain module: the knowledge engine
never touches sessions, uploads, OCR results, or generated PDFs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Corpus (input side)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SourcePage:
    """One page (PDF) or the whole body (md/txt) of a corpus document."""

    page_number: int  # 1-based; text files are a single "page 1"
    text: str


@dataclass(frozen=True)
class SourceDocument:
    """One official reference document loaded from the knowledge corpus."""

    name: str        # human-readable name, e.g. "CVL KYC Form Guide"
    source: str      # where it came from, e.g. "knowledge_docs/cvl-kyc-form-guide.md"
    pages: tuple[SourcePage, ...]


# --------------------------------------------------------------------------- #
# Index (stored side)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class KnowledgeChunk:
    """One semantic chunk of a source document, as stored in the vector DB."""

    chunk_id: str        # stable id: "<doc-slug>-p<page>-c<index>"
    document_name: str   # metadata: which document this text came from
    source: str          # metadata: file path / origin of the document
    page_number: int     # metadata: 1-based page within the document
    chunk_index: int     # metadata: position of the chunk within the document
    text: str


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by similarity search, with its cosine similarity (0-1)."""

    chunk: KnowledgeChunk
    similarity: float


@dataclass(frozen=True)
class KnowledgeAnswer:
    """
    A grounded answer produced from retrieved context ONLY.

    `confident` is False when retrieval could not clear the similarity floor
    (the honest "I don't know" path) — citations are then empty and `answer`
    says so plainly instead of guessing.
    """

    question: str
    answer: str
    confident: bool
    generator: str  # "gpt-4o-mini", "extractive-fallback", or "none"
    citations: tuple[RetrievedChunk, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class IndexReport:
    """Outcome of one ingestion run."""

    documents_indexed: int
    chunks_indexed: int
    document_names: tuple[str, ...]
    embedding_model: str
    elapsed_seconds: float
    indexed_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class KnowledgeStatus:
    """Live snapshot of the knowledge engine for GET /knowledge/status."""

    ready: bool                    # dependencies installed AND index non-empty
    dependencies_installed: bool   # chromadb + sentence-transformers importable
    ai_available: bool             # OpenAI configured (else extractive fallback)
    document_count: int
    chunk_count: int
    embedding_model: str
    vector_db_path: str
    collection: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    min_similarity: float
    last_indexed_at: datetime | None


# --------------------------------------------------------------------------- #
# Ports
# --------------------------------------------------------------------------- #


class EmbeddingProvider(ABC):
    """
    Contract for turning text into vectors (Phase 10).

    The ONLY thing the application knows about embeddings. The concrete model
    (SentenceTransformers today, an API-based embedder tomorrow) lives in
    `app/infrastructure/knowledge/` — no module outside that adapter may
    import sentence_transformers or torch.
    """

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed corpus passages (normalized vectors, one per input text)."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """
        Embed a search query. May differ from document embedding — bge models
        prepend a retrieval instruction to queries but not to passages.
        """

    @abstractmethod
    def model_name(self) -> str:
        """The underlying model identifier for status/report metadata."""


class VectorStore(ABC):
    """
    Contract for persisting and searching chunk vectors (Phase 10).

    ChromaDB implements this today; a pgvector or Qdrant adapter later
    implements the same five methods and nothing in the service changes.
    """

    @abstractmethod
    def rebuild(self, chunks: list[KnowledgeChunk], embeddings: list[list[float]]) -> None:
        """Atomically replace the whole index with these chunks."""

    @abstractmethod
    def search(self, embedding: list[float], top_k: int) -> tuple[RetrievedChunk, ...]:
        """Return the most similar chunks, best first, with cosine similarity."""

    @abstractmethod
    def chunk_count(self) -> int:
        """Number of chunks currently stored (0 = never indexed)."""

    @abstractmethod
    def document_names(self) -> tuple[str, ...]:
        """Distinct document names present in the index (for status)."""

    @abstractmethod
    def last_indexed_at(self) -> datetime | None:
        """When the index was last rebuilt, if the store knows (survives restarts)."""


class CorpusLoader(ABC):
    """
    Contract for reading the official-document corpus off its source (Phase 10).

    The filesystem adapter reads .md/.txt whole and .pdf page-by-page (via
    PyMuPDF, confined to infrastructure exactly like Phase 7's inspector).
    """

    @abstractmethod
    def load(self, directory: str) -> tuple[SourceDocument, ...]:
        """Load every ingestible document; empty tuple if none exist."""
