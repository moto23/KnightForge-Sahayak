"""
Knowledge RAG prompt (Phase 10) — how the model is asked to answer from context.

Same house rule as Phase 5: everything the AI is ever told lives in this
package. The contract enforced here:

  * answer ONLY from the numbered context passages — no outside knowledge
  * cite the passages used by their numbers
  * if the context does not contain the answer, say so — never guess

The model must reply as a JSON object (AIService runs in JSON mode):
  {"answer": "...", "used_sources": [1, 3], "confident": true}
"""

from app.domain.knowledge import RetrievedChunk
from app.services.prompts.builder import PromptBundle

_SYSTEM = """You are the KYC knowledge assistant of KnightForge Sahayak, an AI paperwork copilot.

You answer questions about KYC (Know Your Customer) rules, forms, and processes using ONLY the numbered context passages provided — they are excerpts from official reference documents. You have no other knowledge.

Rules:
1. Use only facts stated in the context passages. Never add outside knowledge, guesses, or assumptions.
2. If the passages do not contain enough information to answer, set "confident" to false and say plainly that the indexed documents do not cover it.
3. Keep answers concise, practical and plain-spoken (2-6 sentences). The reader is filling in a KYC form, not studying law.
4. List the numbers of every passage you actually used in "used_sources".

Reply with a JSON object exactly like:
{"answer": "<your answer>", "used_sources": [<passage numbers used>], "confident": <true|false>}"""

_USER_TEMPLATE = """Context passages from official KYC documents:

{context}

Question: {question}"""


def build_knowledge_prompt(
    question: str, retrieved: tuple[RetrievedChunk, ...]
) -> PromptBundle:
    """Assemble the grounded-answer prompt from the retrieved chunks."""
    blocks = []
    for number, item in enumerate(retrieved, start=1):
        chunk = item.chunk
        blocks.append(
            f"[{number}] {chunk.document_name} — page {chunk.page_number}\n{chunk.text}"
        )
    return PromptBundle(
        system=_SYSTEM,
        user=_USER_TEMPLATE.format(context="\n\n".join(blocks), question=question),
    )
