# Prompt Design — AI Conversation Engine (Phase 5)

How KnightForge Sahayak talks to OpenAI, and why it is safe to let it talk at all.

## The one rule everything follows

**The AI has zero authority.** The deterministic engines built in Phases 2–4 decide
everything that matters:

| Decision | Owner | AI's role |
|---|---|---|
| Which question comes next | NextQuestionEngine (schema order) | phrase it nicely |
| Is an answer valid | Validation Engine (11 deterministic rules) | explain the verdict |
| Is the interview complete | SessionService `_refresh()` | congratulate the user |
| What a field means | Schema Registry (`help_text`, options, examples) | say it conversationally |
| What the user answered | AI extracts a candidate → **validator judges it** | read natural language |

If OpenAI is down, misconfigured, or returns garbage, every endpoint still answers
using deterministic fallback phrasing built from the same schema metadata
(`ai_generated: false` in the response marks this).

## Module layout

```
app/services/prompts/
├── templates.py   # raw building blocks — plain str.format strings, zero logic
├── builder.py     # PromptBuilder — assembles blocks into PromptBundle(system, user)
app/services/ai_service.py        # the ONLY module that calls OpenAI (JSON mode)
app/services/conversation_service.py  # orchestration + fallbacks
```

## Anatomy of every prompt

Every prompt = **one shared system persona** + **one task template** filled with
**standard context blocks**:

```
SYSTEM  = persona("Sahayak") + strict rules + {language_instruction}
USER    = TASK sentence
        + FIELD block     (id, name, type, required, help_text, example,
                           validation rule in words, allowed options)
        + PROGRESS block  (numbers computed by the backend, quoted verbatim)
        + HISTORY block   (last 10 conversation turns)
        + OUTPUT JSON contract
```

This satisfies the Phase 5 requirement that every prompt includes: current field
metadata, help_text, validation rules, previous conversation, and interview progress.

### The system persona (shared by all five tasks)

- Warm, patient, short replies — the audience is someone intimidated by paperwork.
- **Strict rules section**: never decide next question / validity / completion;
  never invent fields, options, or rules not present in the context; never ask for
  extra information; no legal/financial advice.
- One `{language_instruction}` slot — the only thing that varies per language.
- "Reply with ONLY a single JSON object…" — reinforced mechanically by OpenAI
  JSON mode (`response_format={"type": "json_object"}`).

### The five task templates

| Template | Job | Output contract |
|---|---|---|
| `ASK_QUESTION_TEMPLATE` | phrase the engine-chosen next question | `{"message": ...}` |
| `EXPLAIN_FIELD_TEMPLATE` | what/why/format of one field, then re-ask | `{"message": ...}` |
| `EXTRACT_ANSWER_TEMPLATE` | free text → normalized machine value | `{"field_id", "value", "confidence", "intent"}` |
| `CLARIFY_INVALID_TEMPLATE` | gently deliver a validator rejection | `{"message": ...}` |
| `SUMMARIZE_PROGRESS_TEMPLATE` | narrate given progress numbers | `{"message": ...}` |

Notable per-template guardrails:

- **Extract** is the only task returning data, so it gets the tightest rules:
  strip filler words, compact PAN/Aadhaar/mobile/pincode, dates → `YYYY-MM-DD`,
  choice fields → option **value** (not label), booleans → `yes`/`no`
  (haan/ji → yes, nahi → no), and *"NEVER invent a value the user did not say"*.
  It also classifies `intent`: `"answer"` vs `"question"` — how /conversation/reply
  knows to explain instead of submit. Even then, the service **pins `field_id` to
  the field the engine asked about**, ignoring any field the model might pick.
- **Clarify** is told the answer *"was definitively rejected — do NOT claim it
  might be fine"*, preventing the model from contradicting the validator.
- **Summarize** must *"use ONLY the numbers given — never recompute or guess"*.
- **Validation rules reach the model as words**, via `VALIDATION_RULE_TEXT`
  (e.g. PAN → "exactly 10 characters — 5 letters, 4 digits, then 1 letter"), so it
  can explain a format without ever executing a check.

## Structured JSON, enforced twice

1. **At the API call**: JSON mode makes free-form prose impossible.
2. **At the boundary**: the reply is parsed into a Pydantic contract
   (`_MessagePayload` / `_ExtractionPayload`). Anything that doesn't fit —
   wrong keys, wrong types, invalid `confidence`/`intent` — is treated exactly
   like an outage and triggers the fallback. Malformed AI output can never
   reach a user or the Session Engine.

## Language support

`language` (`english` | `hinglish` | `hindi`) selects one instruction line in the
system prompt; everything else is language-independent. Field ids, stored answers,
and validation never change with language. Deterministic fallbacks carry their own
small phrase tables for all three languages (schema `help_text` stays in English
inside fallback messages — an accepted MVP trade-off).

## Graceful degradation

`AIService.complete_json()` collapses every failure mode — missing API key, network
error, auth/rate-limit, timeout (20 s cap, 1 retry), unparseable JSON — into a
single `AIUnavailableError`. `ConversationService` catches it in exactly one place
per task and switches to fallback phrasing. Fallback extraction uses conservative
heuristics (trim, compact numbers, uppercase PAN, match option labels, map yes/no
words, `?` → question intent); the Validation Engine remains the safety net for
whatever the heuristics get wrong.

## Why prompts stay this small

- **Modular**: tune any task's wording without touching the others.
- **Testable**: `PromptBuilder` is pure string assembly — prompts can be asserted
  as plain text in unit tests, no mocking.
- **Cheap**: history capped at 10 turns, replies capped at 400 tokens,
  temperature 0.4 (warm phrasing, not creative writing).
- **Auditable**: `templates.py` is the complete list of everything the model is
  ever told. There is no second place where prompt text hides.
