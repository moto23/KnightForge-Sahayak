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
import re

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


# Provider messages can echo request content and URLs; keep the server log
# useful but never verbose, and never let it reach the user.
_QUOTA_MARKERS = ("RESOURCE_EXHAUSTED", "429", "quota")


def _sanitize(exc: Exception) -> str:
    """A short, safe description of a provider failure for logs/telemetry."""
    text = str(exc)
    if any(marker in text for marker in _QUOTA_MARKERS):
        return "quota/rate limit reached (429)"
    if "API key" in text or "PERMISSION_DENIED" in text or "401" in text:
        return "authentication rejected"
    if "404" in text or "NOT_FOUND" in text:
        return "configured model unavailable (404)"
    if "timeout" in text.lower() or "deadline" in text.lower():
        return "provider timeout"
    return text.split("\n", 1)[0][:160]


def _loads_tolerant(content: str) -> dict:
    """
    Parse a model's JSON reply, repairing the two ways it realistically breaks.

    Even in forced-JSON mode the API can hand back a reply whose tail is
    missing — an object that ends at `"extras": {}` with its closing braces
    never delivered — and some models still wrap the object in ```json fences.
    A strict json.loads() turns both into "the AI is unavailable", silently
    discarding a perfectly good extraction.

    Strategy: try strict first (the overwhelmingly common path, unchanged),
    then unwrap fences, then close any structures the reply left open. Nothing
    is invented — only delimiters the model owed us are appended.
    """
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ```json ... ``` fences, or prose around the object.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text.strip())
    start = text.find("{")
    if start == -1:
        raise AIUnavailableError("Model reply contained no JSON object.")
    text = text[start:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Truncated tail: walk the text tracking string state, then close what is
    # still open in reverse order. A cut mid-string is closed first.
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack:
            stack.pop()
    repaired = text
    if in_string:
        repaired += '"'
    # A dangling `"key":` or trailing comma would still fail — drop it.
    repaired = re.sub(r",\s*$", "", repaired.rstrip())
    repaired = re.sub(r',?\s*"[^"]*"\s*:\s*$', "", repaired.rstrip())
    repaired += "".join(reversed(stack))
    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as exc:
        raise AIUnavailableError(f"Model returned unparseable JSON: {exc}") from exc
    logger.info("Repaired a truncated model JSON reply (%d chars).", len(content))
    return data


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
            data = _loads_tolerant(content)
        except Exception as exc:  # network/auth/timeout/JSON — all mean "no AI"
            logger.warning("Gemini call failed: %s", _sanitize(exc))
            raise AIUnavailableError(_sanitize(exc)) from exc
        if not isinstance(data, dict):
            raise AIUnavailableError("Model returned JSON that is not an object.")
        return data


# Composed once in core/dependencies.py; module-level singleton kept out on
# purpose — AIService reads settings, and tests inject their own.
