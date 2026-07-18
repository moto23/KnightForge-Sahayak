"""
AIService (Phase 5) — the ONLY module in the codebase that talks to the LLM
(Google Gemini, via the google-genai SDK).

Deliberately tiny: one method, `complete_json(bundle) -> dict`. It sends a
PromptBundle with a forced-JSON response (response_mime_type
"application/json") and returns the parsed object. Everything that can go
wrong — no API key configured, network down, auth/rate-limit errors, a
timeout, or the model returning unparseable output — collapses into one
exception, AIUnavailableError, so callers (ConversationService,
KnowledgeService) have exactly one branch: try the AI, fall back to
deterministic phrasing.

AIUnavailableError is intentionally NOT a DomainError: it must never reach the
HTTP layer as an error response. Requirement: if Gemini is unavailable the API
still answers, just less lyrically.
"""

import json
import logging

from app.core.config import Settings, settings
from app.services.prompts import PromptBundle

try:  # Guarded so a missing/broken install degrades to the fallback, not a crash.
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Low-ish temperature: we want warm phrasing, not creative writing — and
# extraction must be as deterministic as an LLM call can be.
TEMPERATURE = 0.4
MAX_OUTPUT_TOKENS = 400


class AIUnavailableError(Exception):
    """The AI could not produce a usable JSON reply — use the fallback."""


class AIService:
    """Thin JSON-mode wrapper around the Google GenAI (Gemini) API."""

    def __init__(self, config: Settings = settings) -> None:
        self._model = config.GEMINI_MODEL
        self._client = None
        if config.GEMINI_API_KEY and genai is not None:
            self._client = genai.Client(
                api_key=config.GEMINI_API_KEY,
                # HttpOptions.timeout is in milliseconds — fail fast into the
                # fallback, don't hang the interview.
                http_options=genai_types.HttpOptions(
                    timeout=int(config.GEMINI_TIMEOUT_SECONDS * 1000),
                ),
            )
        else:
            logger.warning(
                "GEMINI_API_KEY not configured — AI disabled, conversation "
                "endpoints will serve deterministic fallback responses."
            )

    @property
    def is_available(self) -> bool:
        """True when a client exists (key configured and SDK importable)."""
        return self._client is not None

    def complete_json(
        self, bundle: PromptBundle, max_output_tokens: int | None = None
    ) -> dict:
        """
        Send one prompt bundle, force a JSON object reply, parse and return it.

        `max_output_tokens` overrides the small conversational default —
        document extraction (Phase 13) returns much larger JSON objects.

        Raises AIUnavailableError on ANY failure mode.
        """
        if self._client is None:
            raise AIUnavailableError("Gemini is not configured (no API key).")
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=bundle.user,
                config=genai_types.GenerateContentConfig(
                    system_instruction=bundle.system,
                    temperature=TEMPERATURE,
                    max_output_tokens=max_output_tokens or MAX_OUTPUT_TOKENS,
                    response_mime_type="application/json",
                    # Gemini 2.5 "thinking" would silently eat the small output
                    # budget above; these replies are short JSON — disable it.
                    thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
                ),
            )
            content = response.text or ""
            data = json.loads(content)
        except Exception as exc:  # network/auth/timeout/JSON — all mean "no AI"
            import traceback

            traceback.print_exc()
            logger.exception("Gemini call failed")
            raise AIUnavailableError(str(exc)) from exc
        if not isinstance(data, dict):
            raise AIUnavailableError("Model returned JSON that is not an object.")
        return data


# Composed once in core/dependencies.py; module-level singleton kept out on
# purpose — AIService reads settings, and tests inject their own.
