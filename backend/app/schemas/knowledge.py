"""
Knowledge RAG schemas (Phase 10) — typed request/response models for /knowledge.

Same conventions as every other schema module: Pydantic models with described
fields (they render in Swagger), `from_domain` constructors so routes never
hand-map dataclasses, and no domain object ever leaks into a response.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.knowledge import (
    IndexReport,
    KnowledgeAnswer,
    KnowledgeStatus,
    RetrievedChunk,
)

# Keep cited snippets readable in the UI — full chunks are ~900 chars.
_SNIPPET_CHARS = 280


class KnowledgeIndexResponse(BaseModel):
    """Outcome of rebuilding the knowledge index."""

    documents_indexed: int = Field(..., description="Documents ingested from the corpus.")
    chunks_indexed: int = Field(..., description="Semantic chunks written to the vector DB.")
    document_names: list[str] = Field(..., description="Names of the indexed documents.")
    embedding_model: str = Field(..., description="Local model used to embed the chunks.")
    elapsed_seconds: float = Field(..., description="Wall-clock time of the full rebuild.")
    indexed_at: datetime = Field(..., description="When this index was built (UTC).")

    @classmethod
    def from_report(cls, report: IndexReport) -> "KnowledgeIndexResponse":
        return cls(
            documents_indexed=report.documents_indexed,
            chunks_indexed=report.chunks_indexed,
            document_names=list(report.document_names),
            embedding_model=report.embedding_model,
            elapsed_seconds=report.elapsed_seconds,
            indexed_at=report.indexed_at,
        )


class KnowledgeQueryRequest(BaseModel):
    """A question for the knowledge engine."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="The user's question about KYC rules, forms, or process.",
    )
    top_k: int | None = Field(
        None,
        ge=1,
        le=10,
        description="How many chunks to retrieve (default: server setting).",
    )


class KnowledgeCitation(BaseModel):
    """One source passage the answer is grounded in."""

    document_name: str = Field(..., description="Which official document the passage is from.")
    source: str = Field(..., description="Origin of the document (file path).")
    page_number: int = Field(..., description="1-based page within the document.")
    similarity: float = Field(..., description="Cosine similarity of the passage to the question (0-1).")
    snippet: str = Field(..., description="Short excerpt of the cited passage.")

    @classmethod
    def from_retrieved(cls, item: RetrievedChunk) -> "KnowledgeCitation":
        snippet = " ".join(item.chunk.text.split())
        if len(snippet) > _SNIPPET_CHARS:
            snippet = snippet[:_SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
        return cls(
            document_name=item.chunk.document_name,
            source=item.chunk.source,
            page_number=item.chunk.page_number,
            similarity=round(item.similarity, 3),
            snippet=snippet,
        )


class KnowledgeQueryResponse(BaseModel):
    """A grounded answer with its citations — or an honest 'I don't know'."""

    question: str = Field(..., description="The question, echoed back.")
    answer: str = Field(..., description="Answer generated from retrieved context only.")
    confident: bool = Field(
        ...,
        description="False when retrieval/generation could not ground an answer "
        "(the answer then says 'I don't know' rather than guessing).",
    )
    generator: str = Field(
        ...,
        description="What produced the answer: the LLM model name, "
        "'extractive-fallback' (AI offline), or 'none' (below similarity floor).",
    )
    citations: list[KnowledgeCitation] = Field(
        ..., description="Source passages the answer is based on (empty when unconfident)."
    )

    @classmethod
    def from_answer(cls, answer: KnowledgeAnswer) -> "KnowledgeQueryResponse":
        return cls(
            question=answer.question,
            answer=answer.answer,
            confident=answer.confident,
            generator=answer.generator,
            citations=[KnowledgeCitation.from_retrieved(c) for c in answer.citations],
        )


class KnowledgeStatusResponse(BaseModel):
    """Live snapshot of the knowledge engine."""

    ready: bool = Field(..., description="True when dependencies are installed AND the index is non-empty.")
    dependencies_installed: bool = Field(..., description="chromadb + sentence-transformers importable.")
    ai_available: bool = Field(..., description="OpenAI configured; otherwise answers are extractive.")
    document_count: int = Field(..., description="Distinct documents in the index.")
    chunk_count: int = Field(..., description="Chunks in the vector database.")
    embedding_model: str = Field(..., description="Configured local embedding model.")
    vector_db_path: str = Field(..., description="On-disk location of the ChromaDB store.")
    collection: str = Field(..., description="Chroma collection name.")
    chunk_size: int = Field(..., description="Max characters per chunk.")
    chunk_overlap: int = Field(..., description="Characters carried between consecutive chunks.")
    top_k: int = Field(..., description="Default number of chunks retrieved per query.")
    min_similarity: float = Field(..., description="Similarity floor below which the engine says 'I don't know'.")
    last_indexed_at: datetime | None = Field(None, description="When the index was last rebuilt (UTC).")

    @classmethod
    def from_status(cls, status: KnowledgeStatus) -> "KnowledgeStatusResponse":
        return cls(
            ready=status.ready,
            dependencies_installed=status.dependencies_installed,
            ai_available=status.ai_available,
            document_count=status.document_count,
            chunk_count=status.chunk_count,
            embedding_model=status.embedding_model,
            vector_db_path=status.vector_db_path,
            collection=status.collection,
            chunk_size=status.chunk_size,
            chunk_overlap=status.chunk_overlap,
            top_k=status.top_k,
            min_similarity=status.min_similarity,
            last_indexed_at=status.last_indexed_at,
        )
