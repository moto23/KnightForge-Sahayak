"""
OnnxEmbedder — a torch-free EmbeddingProvider adapter.

Why this exists
---------------
`SentenceTransformerEmbedder` is functionally fine but costs ~512 MB of RSS:
importing `sentence_transformers` alone pulls torch, transformers and sklearn
for ~375 MB before a single weight is read, and the bge-small weights add
~137 MB more. That put the whole backend at a measured 658 MB peak, above the
512 MB ceiling of every free hosting tier we could verify.

This adapter runs the same class of model through ONNX Runtime instead, which
ChromaDB already ships and depends on, so it adds no new dependency. Measured
cost is ~215 MB including a full encode, with torch never imported.

What actually changes
---------------------
The embedding MODEL changes from BAAI/bge-small-en-v1.5 to all-MiniLM-L6-v2.
Both produce 384-dimensional L2-normalized vectors, so the vector store schema
and the cosine-similarity thresholds in `Settings` remain meaningful. Nothing
else about Knowledge Chat changes: retrieval, the confidence gate, citation
handling and Gemini generation are untouched.

IMPORTANT: embeddings from different models are not comparable. Switching
embedder REQUIRES re-ingesting the knowledge corpus so every stored vector
comes from this model. A mixed index silently returns nonsense.

Unlike bge, all-MiniLM-L6-v2 is a SYMMETRIC retriever: it is trained with the
same encoder for queries and passages, so no retrieval instruction is
prepended to queries. That asymmetry was a bge-specific detail and correctly
disappears with the model.
"""

import logging
import threading

from app.core.exceptions import KnowledgeUnavailableError
from app.domain.knowledge import EmbeddingProvider

try:  # Optional heavy dependency — absence degrades, never crashes.
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
except ImportError:  # pragma: no cover
    ONNXMiniLM_L6_V2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# The model ChromaDB's bundled ONNX runtime serves. Named here so
# `model_name()` reports the truth rather than a configured alias.
_MODEL_NAME = "all-MiniLM-L6-v2"


class OnnxEmbedder(EmbeddingProvider):
    """Local, offline embedding provider on ONNX Runtime (no torch)."""

    def __init__(self, model_name: str | None = None) -> None:
        # `model_name` is accepted so the composition root can pass
        # settings.KNOWLEDGE_EMBEDDING_MODEL uniformly, but this adapter
        # serves exactly one bundled model and reports that, never the
        # configured value — claiming to run bge while running MiniLM would
        # make the status endpoint lie.
        if model_name and _MODEL_NAME not in model_name:
            logger.info(
                "OnnxEmbedder serves '%s'; configured '%s' is ignored.",
                _MODEL_NAME,
                model_name,
            )
        self._embedder = None
        self._lock = threading.Lock()

    @staticmethod
    def dependencies_installed() -> bool:
        """True when ChromaDB's ONNX embedding function is importable."""
        return ONNXMiniLM_L6_V2 is not None

    def _get_embedder(self):
        """Load once, on first use (double-checked under a lock)."""
        if self._embedder is None:
            if ONNXMiniLM_L6_V2 is None:
                raise KnowledgeUnavailableError(
                    "chromadb is not installed (pip install chromadb)."
                )
            with self._lock:
                if self._embedder is None:
                    logger.info("Loading ONNX embedding model (first use)…")
                    self._embedder = ONNXMiniLM_L6_V2()
                    logger.info("ONNX embedding model ready.")
        return self._embedder

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed corpus passages. Normalized so cosine == dot product."""
        if not texts:
            return []
        vectors = self._get_embedder()(texts)
        return [list(map(float, vector)) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed one query. Symmetric model — no retrieval instruction."""
        return self.embed_documents([text])[0]

    def model_name(self) -> str:
        return _MODEL_NAME
