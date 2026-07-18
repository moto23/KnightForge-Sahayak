"""
SentenceTransformerEmbedder — the EmbeddingProvider adapter (Phase 10).

The ONLY module allowed to import sentence_transformers. The model is loaded
lazily on first use (loading pulls torch and ~100 MB of weights — that must
never slow down `uvicorn` startup or break environments without the install),
guarded by a lock so concurrent first requests load it exactly once.

bge-family models are asymmetric retrievers: queries get a retrieval
instruction prepended, passages do not. This adapter owns that detail so the
service layer stays model-agnostic.
"""

import logging
import threading

from app.core.exceptions import KnowledgeUnavailableError
from app.domain.knowledge import EmbeddingProvider

try:  # Optional heavy dependency — absence degrades, never crashes.
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover
    SentenceTransformer = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Recommended query prefix for BAAI/bge-*-en-v1.5 retrieval (from the model card).
_BGE_QUERY_INSTRUCTION = (
    "Represent this sentence for searching relevant passages: "
)


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Local, offline embedding provider around sentence-transformers."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    @staticmethod
    def dependencies_installed() -> bool:
        """True when the sentence-transformers package is importable."""
        return SentenceTransformer is not None

    def _get_model(self):
        """Load the model once, on first use (double-checked under a lock)."""
        if self._model is None:
            if SentenceTransformer is None:
                raise KnowledgeUnavailableError(
                    "sentence-transformers is not installed "
                    "(pip install sentence-transformers)."
                )
            with self._lock:
                if self._model is None:
                    logger.info(
                        "Loading embedding model '%s' (first use)…", self._model_name
                    )
                    self._model = SentenceTransformer(self._model_name)
                    logger.info("Embedding model '%s' ready.", self._model_name)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed corpus passages. Normalized so cosine == dot product."""
        model = self._get_model()
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        """Embed one query, with the bge retrieval instruction when applicable."""
        if "bge-" in self._model_name.lower():
            text = _BGE_QUERY_INSTRUCTION + text
        model = self._get_model()
        vector = model.encode(
            text, normalize_embeddings=True, show_progress_bar=False
        )
        return vector.tolist()

    def model_name(self) -> str:
        return self._model_name
