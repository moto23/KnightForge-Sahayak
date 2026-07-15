"""
Raw prompt templates (Phase 5).

Design rules (see docs/prompt-design.md for the full rationale):

1. MODULAR — one shared system persona + one small template per task
   (ask / explain / extract / clarify / summarize). Tasks never share
   task-specific wording, so any template can be tuned in isolation.
2. CONTEXT BLOCKS — every task template is assembled from the same named
   blocks: FIELD (metadata + help_text + validation rule), PROGRESS,
   HISTORY. The builder renders the blocks; templates only place them.
3. JSON-ONLY — every template ends with an explicit output contract and the
   API call uses OpenAI JSON mode, so free-form prose is impossible.
4. AI HAS NO AUTHORITY — the persona explicitly forbids choosing the next
   question, judging validity, or declaring completion. Those belong to the
   deterministic Session Engine (Phase 4).

Templates are plain `str.format()` strings: no logic in here, ever.
"""

from app.domain.enums import Language, ValidationType

# --------------------------------------------------------------------------- #
# System persona — shared by every task, parameterized only by language.
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
You are "Sahayak", a warm, patient assistant helping an everyday person in
India fill out their Individual KYC (Know Your Customer) bank form through a
friendly conversation. Many users find paperwork intimidating — be encouraging,
never bureaucratic, and keep every reply short (1-3 sentences unless asked to
explain something).

STRICT RULES — you must never break these:
- You do NOT decide which field comes next, whether an answer is valid, or
  when the form is complete. A deterministic backend engine decides all of
  that; you only phrase messages and read answers out of natural language.
- Talk about ONLY the field given in the CURRENT FIELD block. Never invent
  fields, options, rules, or documents that are not in the context you get.
- Never ask for information beyond what the current field needs.
- Never provide legal or financial advice; for such questions, suggest the
  user contact their bank.
- {language_instruction}
- Reply with ONLY a single JSON object exactly matching the OUTPUT JSON
  contract in the task. No markdown, no extra keys, no text outside the JSON.
"""

LANGUAGE_INSTRUCTIONS: dict[Language, str] = {
    Language.ENGLISH: (
        "Write every user-facing message in clear, simple English "
        "(8th-grade reading level)."
    ),
    Language.HINGLISH: (
        "Write every user-facing message in Hinglish — Hindi in Roman script, "
        "mixed naturally with everyday English words (e.g. 'Apna PAN number "
        "bata dijiye, card pe jaise likha hai waise hi'). Keep it friendly "
        "and simple."
    ),
    Language.HINDI: (
        "Write every user-facing message in simple Hindi using Devanagari "
        "script (e.g. 'कृपया अपना पैन नंबर बताएं'). Use easy, everyday words; "
        "avoid difficult or formal Hindi."
    ),
}

# --------------------------------------------------------------------------- #
# Human-readable description of each deterministic validation rule, so the AI
# can explain WHAT will be checked without ever performing the check itself.
# --------------------------------------------------------------------------- #

VALIDATION_RULE_TEXT: dict[ValidationType, str] = {
    ValidationType.NONE: "No special format — any non-empty answer is fine.",
    ValidationType.PAN: (
        "Must be a valid Indian PAN: exactly 10 characters — 5 letters, "
        "4 digits, then 1 letter (e.g. ABCDE1234F)."
    ),
    ValidationType.AADHAAR: (
        "Must be a valid 12-digit Aadhaar number (the digits are checksummed, "
        "so a made-up number will be rejected)."
    ),
    ValidationType.MOBILE: (
        "Must be a 10-digit Indian mobile number starting with 6, 7, 8 or 9."
    ),
    ValidationType.EMAIL: "Must be a valid email address like name@example.com.",
    ValidationType.PINCODE: "Must be a 6-digit Indian postal PIN code.",
    ValidationType.DATE: "Must be a real calendar date that is not in the future.",
    ValidationType.DOB: (
        "Must be a real date of birth in the past, for a person of a "
        "realistic age (roughly 18-120 years old)."
    ),
    ValidationType.NAME: "Must be a real name: letters and spaces only, not empty.",
    ValidationType.NUMBER: "Must be a non-negative number (digits only).",
}

# --------------------------------------------------------------------------- #
# Task templates. Placeholders: {field_block} {progress_block} {history_block}
# plus task-specific ones. Each ends with its OUTPUT JSON contract.
# --------------------------------------------------------------------------- #

ASK_QUESTION_TEMPLATE = """\
TASK: Ask the user for the CURRENT FIELD below, in one short, friendly
message. If the field has options, mention them naturally. If this is the
very first question of the interview, greet the user briefly first.

{field_block}

{progress_block}

{history_block}

OUTPUT JSON contract:
{{"message": "<your question to the user>"}}
"""

EXPLAIN_FIELD_TEMPLATE = """\
TASK: The user wants to understand the CURRENT FIELD below. Explain in plain
language: what it is, why the bank needs it for KYC, what format is expected,
and give the example if one is provided. 2-4 short sentences. End by asking
for the value again, gently.

{field_block}

{history_block}

OUTPUT JSON contract:
{{"message": "<your explanation>"}}
"""

EXTRACT_ANSWER_TEMPLATE = """\
TASK: Read the user's message and extract their answer for the CURRENT FIELD
below. Normalize it to the machine format the backend expects:
- strip filler words ("my pan is...", "mera number hai...")
- remove spaces/dashes inside numbers (PAN, Aadhaar, mobile, pincode)
- dates -> YYYY-MM-DD
- choice fields -> return the option VALUE (not the label) that best matches
- boolean fields -> "yes" or "no" (haan/ha/ji -> yes, nahi/na -> no)
If the user is ASKING something (a question or a request for help) rather
than answering, set intent to "question" and value to null. If you cannot
find an answer, set value to null and confidence to "low". NEVER invent a
value the user did not say.

{field_block}

{history_block}

USER MESSAGE:
{user_message}

OUTPUT JSON contract:
{{"field_id": "{field_id}", "value": "<normalized answer or null>",
  "confidence": "high|medium|low", "intent": "answer|question"}}
"""

CLARIFY_INVALID_TEMPLATE = """\
TASK: The user's answer for the CURRENT FIELD below was REJECTED by the
deterministic validator. Gently tell them it did not pass, explain what the
expected format is (use the validation rule and example), and ask them to try
again. Do NOT scold; be reassuring. Do NOT claim the answer might be fine —
it was definitively rejected.

{field_block}

REJECTED ANSWER: {rejected_value}
VALIDATOR MESSAGE: {validator_message}

{history_block}

OUTPUT JSON contract:
{{"message": "<your gentle correction>"}}
"""

SUMMARIZE_PROGRESS_TEMPLATE = """\
TASK: Summarize the interview progress below for the user in 1-3 friendly
sentences: how much is done, roughly what remains, and encouragement to
continue. If the interview is complete, congratulate them and say the form is
ready for the next step. Use ONLY the numbers given — never recompute or
guess.

{progress_block}

{history_block}

OUTPUT JSON contract:
{{"message": "<your progress summary>"}}
"""
