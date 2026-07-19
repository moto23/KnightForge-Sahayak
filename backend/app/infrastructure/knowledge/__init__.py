"""
Knowledge RAG infrastructure (Phase 10).

Concrete adapters for the domain ports in `app/domain/knowledge.py`:

  * OnnxEmbedder                 — torch-free embeddings on ONNX Runtime
  * SentenceTransformerEmbedder  — local embedding model (bge / MiniLM)
  * ChromaVectorStore            — persistent local vector database
  * FileSystemCorpusLoader       — reads .md/.txt/.pdf reference documents

Heavy libraries (sentence-transformers/torch, chromadb, PyMuPDF) are imported
ONLY here, behind guards — a missing install degrades the knowledge feature
to a 503, it never crashes app startup.

`SentenceTransformerEmbedder` is resolved LAZILY through a module-level
__getattr__ (PEP 562). Importing it eagerly would pull sentence_transformers,
and therefore torch, transformers and sklearn — ~375 MB of RSS — even when the
composition root has selected the ONNX adapter and never touches it. The
public API is unchanged: `from app.infrastructure.knowledge import
SentenceTransformerEmbedder` still works and still costs torch, but only for
callers that actually ask for it.
"""

from typing import TYPE_CHECKING

from app.infrastructure.knowledge.chroma_vector_store import ChromaVectorStore
from app.infrastructure.knowledge.filesystem_corpus_loader import (
    FileSystemCorpusLoader,
)
from app.infrastructure.knowledge.onnx_embedder import OnnxEmbedder

if TYPE_CHECKING:  # type checkers resolve it statically; runtime stays lazy.
    from app.infrastructure.knowledge.sentence_transformer_embedder import (
        SentenceTransformerEmbedder,
    )

__all__ = [
    "ChromaVectorStore",
    "FileSystemCorpusLoader",
    "OnnxEmbedder",
    "SentenceTransformerEmbedder",
]


def __getattr__(name: str):
    """Import the torch-backed adapter only when it is actually requested."""
    if name == "SentenceTransformerEmbedder":
        from app.infrastructure.knowledge.sentence_transformer_embedder import (
            SentenceTransformerEmbedder as _STE,
        )

        return _STE
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
