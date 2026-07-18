"""
Knowledge RAG infrastructure (Phase 10).

Concrete adapters for the domain ports in `app/domain/knowledge.py`:

  * SentenceTransformerEmbedder  — local embedding model (bge / MiniLM)
  * ChromaVectorStore            — persistent local vector database
  * FileSystemCorpusLoader       — reads .md/.txt/.pdf reference documents

Heavy libraries (sentence-transformers/torch, chromadb, PyMuPDF) are imported
ONLY here, behind guards — a missing install degrades the knowledge feature
to a 503, it never crashes app startup.
"""

from app.infrastructure.knowledge.chroma_vector_store import ChromaVectorStore
from app.infrastructure.knowledge.filesystem_corpus_loader import (
    FileSystemCorpusLoader,
)
from app.infrastructure.knowledge.sentence_transformer_embedder import (
    SentenceTransformerEmbedder,
)

__all__ = [
    "ChromaVectorStore",
    "FileSystemCorpusLoader",
    "SentenceTransformerEmbedder",
]
