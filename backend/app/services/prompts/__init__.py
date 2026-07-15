"""
Prompt package (Phase 5) — everything the AI is ever told lives here.

`templates.py` holds the raw building blocks; `builder.py` assembles them into
complete prompts. Full design rationale: docs/prompt-design.md.
"""

from app.services.prompts.builder import PromptBuilder, PromptBundle, prompt_builder

__all__ = ["PromptBuilder", "PromptBundle", "prompt_builder"]
