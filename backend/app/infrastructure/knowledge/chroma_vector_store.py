"""
ChromaVectorStore — the VectorStore adapter (Phase 10).

The ONLY module allowed to import chromadb. Uses a PersistentClient so the
index lives on disk (settings.KNOWLEDGE_DB_DIR) and survives restarts — the
corpus only needs re-indexing when the documents change.

The collection is created with cosine distance; `search()` converts Chroma's
distance back into a similarity (1 - distance) so the service layer reasons
in one unit everywhere. The last-index timestamp is persisted in the
collection's metadata, so GET /knowledge/status is truthful after a restart.
"""

import logging
import threading
from datetime import datetime, timezone

from app.core.exceptions import KnowledgeUnavailableError
from app.domain.knowledge import KnowledgeChunk, RetrievedChunk, VectorStore

try:  # Optional heavy dependency — absence degrades, never crashes.
    import chromadb
except ImportError:  # pragma: no cover
    chromadb = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Chroma accepts large batches, but keep adds bounded and predictable.
_ADD_BATCH_SIZE = 256
_LAST_INDEXED_KEY = "last_indexed_at"


class ChromaVectorStore(VectorStore):
    """Persistent local vector database adapter around ChromaDB."""

    def __init__(self, db_path: str, collection_name: str) -> None:
        self._db_path = db_path
        self._collection_name = collection_name
        self._client = None
        self._lock = threading.Lock()

    @staticmethod
    def dependencies_installed() -> bool:
        """True when the chromadb package is importable."""
        return chromadb is not None

    def _get_client(self):
        """Create the persistent client once, on first use."""
        if self._client is None:
            if chromadb is None:
                raise KnowledgeUnavailableError(
                    "chromadb is not installed (pip install chromadb)."
                )
            with self._lock:
                if self._client is None:
                    self._client = chromadb.PersistentClient(path=self._db_path)
        return self._client

    def _get_collection(self):
        return self._get_client().get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------ #
    # VectorStore port
    # ------------------------------------------------------------------ #

    def rebuild(
        self, chunks: list[KnowledgeChunk], embeddings: list[list[float]]
    ) -> None:
        """Drop the old collection and write the new chunks in batches."""
        client = self._get_client()
        try:
            client.delete_collection(self._collection_name)
        except Exception:  # a collection that never existed is fine
            pass
        collection = client.create_collection(
            name=self._collection_name,
            metadata={
                "hnsw:space": "cosine",
                _LAST_INDEXED_KEY: datetime.now(timezone.utc).isoformat(),
            },
        )
        for start in range(0, len(chunks), _ADD_BATCH_SIZE):
            batch = chunks[start : start + _ADD_BATCH_SIZE]
            collection.add(
                ids=[chunk.chunk_id for chunk in batch],
                embeddings=embeddings[start : start + _ADD_BATCH_SIZE],
                documents=[chunk.text for chunk in batch],
                metadatas=[
                    {
                        "document_name": chunk.document_name,
                        "source": chunk.source,
                        "page_number": chunk.page_number,
                        "chunk_index": chunk.chunk_index,
                    }
                    for chunk in batch
                ],
            )
        logger.info(
            "Chroma collection '%s' rebuilt with %d chunks at %s",
            self._collection_name,
            len(chunks),
            self._db_path,
        )

    def search(
        self, embedding: list[float], top_k: int
    ) -> tuple[RetrievedChunk, ...]:
        collection = self._get_collection()
        total = collection.count()
        if total == 0:
            return ()
        result = collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, total),
            include=["documents", "metadatas", "distances"],
        )
        retrieved: list[RetrievedChunk] = []
        for chunk_id, text, metadata, distance in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ):
            chunk = KnowledgeChunk(
                chunk_id=chunk_id,
                document_name=str(metadata.get("document_name", "")),
                source=str(metadata.get("source", "")),
                page_number=int(metadata.get("page_number", 1)),
                chunk_index=int(metadata.get("chunk_index", 0)),
                text=text,
            )
            # Cosine distance -> similarity; clamp against float drift.
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
            retrieved.append(RetrievedChunk(chunk=chunk, similarity=similarity))
        return tuple(retrieved)

    def chunk_count(self) -> int:
        if chromadb is None:
            return 0
        return self._get_collection().count()

    def document_names(self) -> tuple[str, ...]:
        if chromadb is None:
            return ()
        collection = self._get_collection()
        if collection.count() == 0:
            return ()
        records = collection.get(include=["metadatas"])
        names = {
            str(metadata.get("document_name", ""))
            for metadata in records["metadatas"]
            if metadata
        }
        return tuple(sorted(name for name in names if name))

    def last_indexed_at(self) -> datetime | None:
        if chromadb is None:
            return None
        metadata = self._get_collection().metadata or {}
        raw = metadata.get(_LAST_INDEXED_KEY)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            return None
