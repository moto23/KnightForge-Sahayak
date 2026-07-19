"""
KnowledgeService (Phase 10) — the Knowledge RAG engine's use-cases.

Orchestrates the three ports (CorpusLoader -> EmbeddingProvider -> VectorStore)
plus the existing AIService into the module's three operations:

  index()   ingest the official-document corpus: semantic chunking with
            metadata (document name, page number, source), embed locally,
            rebuild the vector index atomically
  query()   retrieve the most relevant chunks, gate on similarity, and
            generate an answer FROM THE RETRIEVED CONTEXT ONLY with citations
            — or an honest "I don't know" when retrieval isn't confident
  status()  live snapshot for the frontend / ops

Grounding guarantees, in order of defense:
  1. similarity floor — chunks below KNOWLEDGE_MIN_SIMILARITY are discarded
  2. relevance gate — cosine similarity alone is NOT trusted (bge scores for
     unrelated text can reach ~0.5): unless the best chunk is VERY similar
     (KNOWLEDGE_STRONG_SIMILARITY), the retrieved context must also share the
     question's content terms (lexical grounding). Failing both means the LLM
     is never called and the user gets a plain "I don't know"
  3. prompt contract — the model may only use the numbered passages, must
     report which ones it used, and its own unconfident verdict is honored
     by returning the canonical "I don't know" (never its guess)
  4. no-AI fallback — if OpenAI is unavailable, a question that PASSED the
     relevance gate degrades to the retrieved passages themselves
     (extractive, verbatim, still cited), matching the app-wide rule that a
     missing API key never breaks a feature

Completely independent of OCR, Session, Upload and PDF services — this module
shares only AIService and the config object with the rest of the app.
"""

import logging
import re
import time

from app.core.config import Settings, settings
from app.core.exceptions import (
    KnowledgeCorpusMissingError,
    KnowledgeIndexEmptyError,
    KnowledgeUnavailableError,
)
from app.domain.knowledge import (
    CorpusLoader,
    EmbeddingProvider,
    IndexReport,
    KnowledgeAnswer,
    KnowledgeChunk,
    KnowledgeStatus,
    RetrievedChunk,
    SourceDocument,
    VectorStore,
)
from app.services.ai_service import AIService, AIUnavailableError
from app.services.knowledge_intent import (
    QueryIntent,
    classify_intent,
    conversational_answer,
    datetime_answer,
)
from app.services.prompts import build_knowledge_prompt

logger = logging.getLogger(__name__)

# The honest answer when retrieval can't ground a response. Never guessed past.
# Scoped to the whole supported domain — not one form — so the user learns
# what this assistant CAN answer.
_IDK_ANSWER = (
    "I don't know based on the current KYC knowledge base. Sahayak focuses on "
    "KYC forms, required documents, identity/address proofs, bank KYC, KRA "
    "rules and using this platform. Try asking about CVL, SBI, HDFC, ICICI or "
    "Axis KYC, PAN/Aadhaar, address proofs, required documents or the KYC "
    "process."
)

# Header for the grounded extractive answer used when generation is
# unavailable. The user is never told the AI is "offline" — they get the
# official wording, cited, which is a legitimate answer in its own right.
_FALLBACK_HEADER = (
    "Here's what the official KYC documents say about this:"
)
_FALLBACK_EXCERPT_CHARS = 350


class KnowledgeService:
    """Use-case layer of the Knowledge RAG engine."""

    def __init__(
        self,
        loader: CorpusLoader,
        embedder: EmbeddingProvider,
        store: VectorStore,
        ai: AIService,
        dependencies_installed: bool,
        config: Settings = settings,
    ) -> None:
        self._loader = loader
        self._embedder = embedder
        self._store = store
        self._ai = ai
        # Whether chromadb + sentence-transformers are importable. Probed once
        # by the composition root (the only place that knows the adapters).
        self._dependencies_installed = dependencies_installed
        self._config = config

    # ------------------------------------------------------------------ #
    # Ingestion
    # ------------------------------------------------------------------ #

    def index(self) -> IndexReport:
        """Chunk + embed the corpus and atomically rebuild the vector index."""
        self._require_dependencies()
        started = time.perf_counter()

        documents = self._loader.load(self._config.KNOWLEDGE_DOCS_DIR)
        if not documents:
            raise KnowledgeCorpusMissingError(self._config.KNOWLEDGE_DOCS_DIR)

        chunks: list[KnowledgeChunk] = []
        for document in documents:
            chunks.extend(self._chunk_document(document))
        logger.info(
            "Knowledge corpus: %d documents -> %d chunks; embedding with %s…",
            len(documents),
            len(chunks),
            self._embedder.model_name(),
        )

        embeddings = self._embedder.embed_documents([c.text for c in chunks])
        self._store.rebuild(chunks, embeddings)

        report = IndexReport(
            documents_indexed=len(documents),
            chunks_indexed=len(chunks),
            document_names=tuple(document.name for document in documents),
            embedding_model=self._embedder.model_name(),
            elapsed_seconds=round(time.perf_counter() - started, 2),
        )
        logger.info(
            "Knowledge index rebuilt: %d chunks from %d documents in %.2fs",
            report.chunks_indexed,
            report.documents_indexed,
            report.elapsed_seconds,
        )
        return report

    def _chunk_document(self, document: SourceDocument) -> list[KnowledgeChunk]:
        """Semantic chunking: paragraph-first packing, sentence fallback, overlap."""
        slug = re.sub(r"[^a-z0-9]+", "-", document.name.lower()).strip("-") or "doc"
        chunks: list[KnowledgeChunk] = []
        chunk_index = 0
        for page in document.pages:
            for text in _chunk_text(
                page.text,
                size=self._config.KNOWLEDGE_CHUNK_SIZE,
                overlap=self._config.KNOWLEDGE_CHUNK_OVERLAP,
            ):
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=f"{slug}-p{page.page_number}-c{chunk_index}",
                        document_name=document.name,
                        source=document.source,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        text=text,
                    )
                )
                chunk_index += 1
        return chunks

    # ------------------------------------------------------------------ #
    # Retrieval + grounded generation
    # ------------------------------------------------------------------ #

    def query(
        self,
        question: str,
        top_k: int | None = None,
        workflow_state: str | None = None,
    ) -> KnowledgeAnswer:
        """Answer from retrieved context only — or say "I don't know" honestly."""
        # Intent routing FIRST: greetings, "who are you?" and date questions
        # have no answer in a KYC corpus, and clearly unrelated questions must
        # never be answered from the model's general knowledge. Only genuine
        # domain questions reach retrieval.
        intent = classify_intent(question)
        if intent is QueryIntent.CONVERSATIONAL:
            return KnowledgeAnswer(
                question=question,
                answer=conversational_answer(question),
                confident=True,
                generator="sahayak-assistant",
                citations=(),
            )
        if intent is QueryIntent.DATETIME:
            return KnowledgeAnswer(
                question=question,
                answer=datetime_answer(question, self._config.APP_TIMEZONE),
                confident=True,
                generator="server-clock",
                citations=(),
            )
        # A question about THIS applicant's own form is answered from the
        # session, never from the corpus and never by the model: retrieval
        # only knows official documents, and a generated guess about
        # someone's progress would be an invented fact about their KYC.
        if intent is QueryIntent.WORKFLOW:
            return KnowledgeAnswer(
                question=question,
                answer=workflow_state or (
                    "I can only answer that once you have a KYC form open. Upload or choose your primary form on the Upload page, and I will tell you exactly what is left."
                ),
                confident=workflow_state is not None,
                generator="session-state",
                citations=(),
            )
        if intent is QueryIntent.OUT_OF_DOMAIN:
            logger.info("Knowledge query routed out-of-domain: %r", question)
            return self._idk(question)

        self._require_dependencies()
        if self._store.chunk_count() == 0:
            raise KnowledgeIndexEmptyError()

        k = top_k or self._config.KNOWLEDGE_TOP_K
        retrieved = self._store.search(self._embedder.embed_query(question), k)

        # Layer 1: similarity floor — discard clearly-off chunks.
        relevant = tuple(
            item
            for item in retrieved
            if item.similarity >= self._config.KNOWLEDGE_MIN_SIMILARITY
        )

        # Layer 2: relevance gate. Cosine similarity alone is NOT sufficient
        # ("capital of France" scores ~0.4 against KYC text), so unless the
        # match is VERY strong the context must also share the question's
        # content terms. Failing this, the LLM is never called — no answer
        # can be forced out of irrelevant context.
        if not relevant or not self._context_is_relevant(question, relevant):
            best = max((item.similarity for item in retrieved), default=0.0)
            logger.info(
                "Knowledge query rejected by relevance gate (best=%.3f): %r",
                best,
                question,
            )
            return self._idk(question)

        try:
            return self._generate(question, relevant)
        except AIUnavailableError:
            # Layer 4: no AI — the gate already passed, so degrading to the
            # retrieved passages themselves keeps the answer grounded.
            return self._extractive_fallback(question, relevant)

    def _context_is_relevant(
        self, question: str, relevant: tuple[RetrievedChunk, ...]
    ) -> bool:
        """
        Decide whether the retrieved context can actually answer the question.

        Two independent signals, either suffices:
          * embedding: the best chunk is VERY similar (strong-similarity bar,
            where bge scores are trustworthy), or
          * lexical: the retrieved text contains a meaningful fraction of the
            question's content terms (stopwords stripped), so the question is
            actually ABOUT something these documents discuss.

        A question whose content terms are entirely absent from the context
        (France, Kohli, cake…) fails both and is refused.
        """
        best = max(item.similarity for item in relevant)
        if best >= self._config.KNOWLEDGE_STRONG_SIMILARITY:
            return True

        terms = _content_terms(question)
        if not terms:
            # Nothing but stopwords ("what is it?") — similarity is all we
            # have, and it wasn't strong enough.
            return False
        context_tokens = _content_terms(
            " ".join(item.chunk.text for item in relevant)
        )
        matched = sum(1 for term in terms if term in context_tokens)
        overlap = matched / len(terms)
        passed = overlap >= self._config.KNOWLEDGE_MIN_TERM_OVERLAP
        logger.debug(
            "Relevance gate: best=%.3f overlap=%.2f (%d/%d terms) -> %s",
            best,
            overlap,
            matched,
            len(terms),
            "pass" if passed else "reject",
        )
        return passed

    @staticmethod
    def _idk(question: str) -> KnowledgeAnswer:
        """The canonical honest refusal: unconfident, uncited, ungenerated."""
        return KnowledgeAnswer(
            question=question,
            answer=_IDK_ANSWER,
            confident=False,
            generator="none",
            citations=(),
        )

    def _generate(
        self, question: str, relevant: tuple[RetrievedChunk, ...]
    ) -> KnowledgeAnswer:
        """Ask the LLM to answer from the numbered passages (JSON mode)."""
        data = self._ai.complete_json(build_knowledge_prompt(question, relevant))
        answer = str(data.get("answer") or "").strip()
        if not answer:
            raise AIUnavailableError("Model returned an empty answer.")

        # Layer 3: honor the model's own verdict. If it judged the passages
        # insufficient, return the canonical refusal — never its guess.
        if not bool(data.get("confident", False)):
            logger.info("Knowledge query judged unanswerable by the model: %r", question)
            return KnowledgeService._idk(question)

        # Cite exactly the passages the model says it used (validated); if it
        # answered confidently but named none, cite everything it was shown.
        used = data.get("used_sources") or []
        cited = tuple(
            relevant[number - 1]
            for number in used
            if isinstance(number, int) and 1 <= number <= len(relevant)
        )
        if not cited:
            cited = relevant
        return KnowledgeAnswer(
            question=question,
            answer=answer,
            confident=True,
            generator=self._config.GEMINI_MODEL,
            citations=cited,
        )

    @staticmethod
    def _extractive_fallback(
        question: str, relevant: tuple[RetrievedChunk, ...]
    ) -> KnowledgeAnswer:
        """Verbatim excerpts of the retrieved chunks — grounded even without AI."""
        lines = [_FALLBACK_HEADER, ""]
        for number, item in enumerate(relevant, start=1):
            excerpt = " ".join(item.chunk.text.split())
            if len(excerpt) > _FALLBACK_EXCERPT_CHARS:
                excerpt = excerpt[:_FALLBACK_EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"
            lines.append(
                f"[{number}] {item.chunk.document_name} (page "
                f"{item.chunk.page_number}): {excerpt}"
            )
        return KnowledgeAnswer(
            question=question,
            answer="\n".join(lines),
            confident=True,  # verbatim from the documents — nothing was guessed
            generator="extractive-fallback",
            citations=relevant,
        )

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def status(self) -> KnowledgeStatus:
        """Live snapshot; safe to call even when the RAG stack isn't installed."""
        chunk_count = 0
        document_count = 0
        last_indexed_at = None
        if self._dependencies_installed:
            try:
                chunk_count = self._store.chunk_count()
                document_count = len(self._store.document_names())
                last_indexed_at = self._store.last_indexed_at()
            except Exception as exc:  # a broken store must not break status
                logger.warning("Knowledge status probe failed: %s", exc)
        return KnowledgeStatus(
            ready=self._dependencies_installed and chunk_count > 0,
            dependencies_installed=self._dependencies_installed,
            ai_available=self._ai.is_available,
            document_count=document_count,
            chunk_count=chunk_count,
            # The ACTIVE adapter's model, not the configured name. The ONNX
            # embedder serves a bundled model and ignores the configured
            # value, so reporting config here told the status endpoint that
            # bge-small was running when MiniLM actually was.
            embedding_model=self._embedder.model_name(),
            vector_db_path=self._config.KNOWLEDGE_DB_DIR,
            collection=self._config.KNOWLEDGE_COLLECTION,
            chunk_size=self._config.KNOWLEDGE_CHUNK_SIZE,
            chunk_overlap=self._config.KNOWLEDGE_CHUNK_OVERLAP,
            top_k=self._config.KNOWLEDGE_TOP_K,
            min_similarity=self._config.KNOWLEDGE_MIN_SIMILARITY,
            last_indexed_at=last_indexed_at,
        )

    def _require_dependencies(self) -> None:
        if not self._dependencies_installed:
            raise KnowledgeUnavailableError(
                "chromadb and/or sentence-transformers are not installed. "
                "Run: pip install chromadb sentence-transformers"
            )


# --------------------------------------------------------------------------- #
# Relevance-gate + semantic chunking helpers (pure functions — unit-testable)
# --------------------------------------------------------------------------- #

# English function words carrying no topical signal. Deliberately small and
# question-oriented — over-aggressive stopword lists start eating domain terms.
_STOPWORDS = frozenset(
    """
    a an and are as at be but by can could did do does for from had has have
    how i if in into is it its may me my not of on or our shall should so
    such than that the their them then there these they this to was we were
    what when where which who whom whose why will with would you your
    """.split()
)


def _stem(word: str) -> str:
    """Tiny deterministic stemmer: strips common English suffixes so
    'performs'/'performed'/'performing' and 'documents'/'document' align.
    Not linguistics — just enough for term matching, with no dependency."""
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith(("ed", "es")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _content_terms(text: str) -> set[str]:
    """The stemmed, lowercased content words of a text (stopwords removed)."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(token) for token in tokens if token not in _STOPWORDS}


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """
    Split text into chunks of at most `size` characters along semantic
    boundaries: paragraphs first, sentences when a paragraph is too long,
    with the previous chunk's last `overlap` characters carried forward so
    a fact straddling a boundary is fully present in at least one chunk.
    """
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= size:
            units.append(paragraph)
        else:
            units.extend(_split_long_paragraph(paragraph, size))

    chunks: list[str] = []
    buffer = ""
    for unit in units:
        candidate = f"{buffer}\n\n{unit}" if buffer else unit
        if len(candidate) > size and buffer:
            chunks.append(buffer)
            buffer = f"{_overlap_tail(buffer, overlap)}{unit}"
        else:
            buffer = candidate
    if buffer:
        chunks.append(buffer)
    return chunks


def _split_long_paragraph(paragraph: str, size: int) -> list[str]:
    """Sentence-pack an oversized paragraph; hard-split monster sentences."""
    pieces: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        while len(sentence) > size:  # pathological unbroken run — hard split
            pieces.append(sentence[:size])
            sentence = sentence[size:]
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > size and current:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(chunk: str, overlap: int) -> str:
    """Last `overlap` characters of a chunk, cut at a word boundary."""
    if overlap <= 0 or len(chunk) <= overlap:
        return ""
    tail = chunk[-overlap:]
    space = tail.find(" ")
    if space != -1:
        tail = tail[space + 1 :]
    tail = tail.strip()
    return f"{tail}\n\n" if tail else ""
