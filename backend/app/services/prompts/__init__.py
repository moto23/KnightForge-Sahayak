"""
Prompt package (Phase 5) — everything the AI is ever told lives here.

`templates.py` holds the raw building blocks; `builder.py` assembles them into
complete prompts. Full design rationale: docs/prompt-design.md.
"""

from app.services.prompts.builder import PromptBuilder, PromptBundle, prompt_builder
from app.services.prompts.chat import build_standalone_question_prompt
from app.services.prompts.knowledge import build_knowledge_prompt

__all__ = [
    "PromptBuilder",
    "PromptBundle",
    "build_knowledge_prompt",
    "build_standalone_question_prompt",
    "prompt_builder",
]
