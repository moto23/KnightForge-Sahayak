"""
AIService (Phase 5) — the ONLY module in the codebase that talks to OpenAI.

Deliberately tiny: one method, `complete_json(bundle) -> dict`. It sends a
PromptBundle in OpenAI JSON mode and returns the parsed object. Everything
that can go wrong — no API key configured, network down, auth/rate-limit
errors, a timeout, or the model returning unparseable output — collapses into
one exception, AIUnavailableError, so callers (ConversationService) have
exactly one branch: try the AI, fall back to deterministic phrasing.

AIUnavailableError is intentionally NOT a DomainError: it must never reach the
HTTP layer as an error response. Requirement: if OpenAI is unavailable the API
still answers, just less lyrically.
"""

import json
import logging

from app.core.config import Settings, settings
from app.services.prompts import PromptBundle

try:  # The SDK is in requirements; guarded anyway so a bad install degrades, not crashes.
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Low-ish temperature: we want warm phrasing, not creative writing — and
# extraction must be as deterministic as an LLM call can be.
TEMPERATURE = 0.4
MAX_OUTPUT_TOKENS = 400


class AIUnavailableError(Exception):
    """The AI could not produce a usable JSON reply — use the fallback."""


class AIService:
    """Thin JSON-mode wrapper around the OpenAI chat completions API."""

    def __init__(self, config: Settings = settings) -> None:
        self._model = config.OPENAI_MODEL
        self._client = None
        if config.OPENAI_API_KEY and OpenAI is not None:
            self._client = OpenAI(
                api_key=config.OPENAI_API_KEY,
                timeout=config.OPENAI_TIMEOUT_SECONDS,
                max_retries=1,  # fail fast into the fallback, don't hang the interview
            )
        else:
            logger.warning(
                "OPENAI_API_KEY not configured — AI disabled, conversation "
                "endpoints will serve deterministic fallback responses."
            )

    @property
    def is_available(self) -> bool:
        """True when a client exists (key configured and SDK importable)."""
        return self._client is not None

    def complete_json(self, bundle: PromptBundle) -> dict:
        """
        Send one prompt bundle, force a JSON object reply, parse and return it.

        Raises AIUnavailableError on ANY failure mode.
        """
        if self._client is None:
            raise AIUnavailableError("OpenAI is not configured (no API key).")
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": bundle.system},
                    {"role": "user", "content": bundle.user},
                ],
            )
            content = response.choices[0].message.content or ""
            data = json.loads(content)
        except Exception as exc:  # network/auth/timeout/JSON — all mean "no AI"
            logger.warning("OpenAI call failed, falling back: %s", exc)
            raise AIUnavailableError(str(exc)) from exc
        if not isinstance(data, dict):
            raise AIUnavailableError("Model returned JSON that is not an object.")
        return data


# Composed once in core/dependencies.py; module-level singleton kept out on
# purpose — AIService reads settings, and tests inject their own.
