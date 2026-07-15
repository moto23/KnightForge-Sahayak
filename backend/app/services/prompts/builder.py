"""
PromptBuilder (Phase 5) — assembles complete prompts from the raw templates.

Every prompt the AI ever sees is built here and only here. Each build method
returns a PromptBundle(system, user) where:

- `system` = the shared Sahayak persona + the language instruction, and
- `user`   = the task template with the standard context blocks filled in:
    FIELD    — current field metadata, help_text, validation rule, options
    PROGRESS — interview progress numbers from the deterministic engine
    HISTORY  — the last few conversation turns, for continuity

The builder is pure string assembly: it performs no I/O, calls no model, and
never mutates state — which makes every prompt unit-testable as plain text.
"""

from dataclasses import dataclass

from app.domain.conversation import ConversationTurn
from app.domain.enums import Language
from app.domain.models import KYCField
from app.services.prompts import templates

# Keep prompts small: only the most recent turns matter for continuity.
MAX_HISTORY_TURNS = 10


@dataclass(frozen=True)
class PromptBundle:
    """A ready-to-send prompt pair: system persona + task message."""

    system: str
    user: str


class PromptBuilder:
    """Builds one PromptBundle per AI task, from shared context blocks."""

    # ------------------------------------------------------------------ #
    # Task prompts
    # ------------------------------------------------------------------ #

    def ask_question(
        self,
        field: KYCField,
        progress_percentage: float,
        answered_required: int,
        total_required: int,
        history: tuple[ConversationTurn, ...],
        language: Language,
    ) -> PromptBundle:
        """Prompt to phrase the next interview question conversationally."""
        user = templates.ASK_QUESTION_TEMPLATE.format(
            field_block=self._field_block(field),
            progress_block=self._progress_block(
                progress_percentage, answered_required, total_required
            ),
            history_block=self._history_block(history),
        )
        return PromptBundle(system=self._system(language), user=user)

    def explain_field(
        self,
        field: KYCField,
        history: tuple[ConversationTurn, ...],
        language: Language,
    ) -> PromptBundle:
        """Prompt to explain what a field means and why the bank needs it."""
        user = templates.EXPLAIN_FIELD_TEMPLATE.format(
            field_block=self._field_block(field),
            history_block=self._history_block(history),
        )
        return PromptBundle(system=self._system(language), user=user)

    def extract_answer(
        self,
        field: KYCField,
        user_message: str,
        history: tuple[ConversationTurn, ...],
        language: Language,
    ) -> PromptBundle:
        """Prompt to pull a normalized machine value out of natural language."""
        user = templates.EXTRACT_ANSWER_TEMPLATE.format(
            field_block=self._field_block(field),
            history_block=self._history_block(history),
            user_message=user_message,
            field_id=field.id,
        )
        return PromptBundle(system=self._system(language), user=user)

    def clarify_invalid_input(
        self,
        field: KYCField,
        rejected_value: str | None,
        validator_message: str,
        history: tuple[ConversationTurn, ...],
        language: Language,
    ) -> PromptBundle:
        """Prompt to gently explain a rejected answer and re-ask."""
        user = templates.CLARIFY_INVALID_TEMPLATE.format(
            field_block=self._field_block(field),
            rejected_value=rejected_value if rejected_value is not None else "(empty)",
            validator_message=validator_message,
            history_block=self._history_block(history),
        )
        return PromptBundle(system=self._system(language), user=user)

    def summarize_progress(
        self,
        progress_percentage: float,
        answered_required: int,
        total_required: int,
        pending_field_names: tuple[str, ...],
        completed: bool,
        history: tuple[ConversationTurn, ...],
        language: Language,
    ) -> PromptBundle:
        """Prompt to narrate the deterministic progress numbers."""
        progress = self._progress_block(
            progress_percentage, answered_required, total_required
        )
        if completed:
            progress += "\nSTATUS: the interview is COMPLETE — every required field is filled."
        elif pending_field_names:
            progress += "\nSTILL PENDING (in order): " + ", ".join(pending_field_names)
        user = templates.SUMMARIZE_PROGRESS_TEMPLATE.format(
            progress_block=progress,
            history_block=self._history_block(history),
        )
        return PromptBundle(system=self._system(language), user=user)

    # ------------------------------------------------------------------ #
    # Shared context blocks
    # ------------------------------------------------------------------ #

    def _system(self, language: Language) -> str:
        return templates.SYSTEM_PROMPT.format(
            language_instruction=templates.LANGUAGE_INSTRUCTIONS[language]
        )

    def _field_block(self, field: KYCField) -> str:
        """Render everything the AI may know about the current field."""
        lines = [
            "CURRENT FIELD:",
            f"- id: {field.id}",
            f"- name: {field.display_name}",
            f"- section: {field.section.value}",
            f"- input type: {field.field_type.value}",
            f"- required: {'yes' if field.required else 'no'}",
        ]
        if field.help_text:
            lines.append(f"- help_text: {field.help_text}")
        if field.example:
            lines.append(f"- example of a valid value: {field.example}")
        rule = templates.VALIDATION_RULE_TEXT.get(field.validation_type)
        if rule:
            lines.append(f"- validation rule (checked by the backend, not you): {rule}")
        if field.options:
            options = "; ".join(
                f"value={option.value} label={option.label}" for option in field.options
            )
            lines.append(f"- allowed options: {options}")
        return "\n".join(lines)

    def _progress_block(
        self,
        progress_percentage: float,
        answered_required: int,
        total_required: int,
    ) -> str:
        return (
            "INTERVIEW PROGRESS (computed by the backend — quote, never recompute):\n"
            f"- {answered_required} of {total_required} required fields answered "
            f"({progress_percentage}% complete)"
        )

    def _history_block(self, history: tuple[ConversationTurn, ...]) -> str:
        """Render the last MAX_HISTORY_TURNS turns, oldest first."""
        recent = history[-MAX_HISTORY_TURNS:]
        if not recent:
            return "CONVERSATION SO FAR: (none — this is the start)"
        lines = ["CONVERSATION SO FAR (oldest first):"]
        lines += [f"- {turn.role.value}: {turn.content}" for turn in recent]
        return "\n".join(lines)


# Stateless singleton — safe to share across requests.
prompt_builder = PromptBuilder()
