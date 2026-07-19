"""
ConversationService (Phase 5) — natural language in, natural language out,
with ZERO authority over the interview.

Division of power, enforced by construction:

- Session Engine (Phase 4)  decides next question, validity, completion.
- Validation Engine (Phase 3) is the only judge of any answer.
- The AI (this layer)       only phrases questions, explains fields, extracts
                            a machine value from free text, and narrates
                            progress numbers it is given.

Every method follows the same shape: gather deterministic facts from
InterviewService, build a prompt with PromptBuilder, try AIService, and fall
back to schema-driven canned phrasing when the AI is unavailable or returns
malformed JSON. The API therefore NEVER fails because OpenAI is down — replies
just get less lyrical (`ai_generated: false`).
"""

import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.domain.conversation import ConversationTurn, TurnRole
from app.domain.enums import FieldType, Language, ValidationType
from app.domain.models import KYCField
from app.domain.repositories import ConversationRepository
from app.domain.session import Session
from app.domain.validators.result import ValidationResult
from app.services.ai_service import AIService, AIUnavailableError
from app.services.form_service import FormService, form_service
from app.services.interview_service import InterviewService, ProgressReport
from app.services.prompts import PromptBuilder, PromptBundle, prompt_builder
from app.services.prompts.templates import VALIDATION_RULE_TEXT

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Contracts for the JSON the AI must return. If its output does not parse into
# these models it is treated exactly like an outage: fall back, never trust.
# --------------------------------------------------------------------------- #


class _MessagePayload(BaseModel):
    """Every phrasing task returns exactly one key: the message."""

    message: str


class _ExtractionPayload(BaseModel):
    """The extraction task returns a normalized value + how it was meant."""

    field_id: str
    value: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    intent: Literal["answer", "question"] = "answer"


# --------------------------------------------------------------------------- #
# Results handed to the API layer.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ExtractedAnswer:
    """A machine value pulled out of a natural-language message."""

    field_id: str
    value: str | None
    confidence: str            # high | medium | low
    intent: str                # answer | question
    ai_generated: bool


@dataclass(frozen=True)
class ConversationOpening:
    """Result of starting a conversation: new session + phrased first question."""

    session: Session
    question: KYCField | None
    message: str
    ai_generated: bool


@dataclass(frozen=True)
class FieldExplanation:
    """A plain-language explanation of one field (None once the interview is done)."""

    field: KYCField | None
    message: str
    ai_generated: bool


@dataclass(frozen=True)
class ProgressSummary:
    """The deterministic progress report plus its conversational narration."""

    report: ProgressReport
    message: str
    ai_generated: bool


@dataclass(frozen=True)
class ConversationReply:
    """Everything that happened for one user message."""

    session: Session
    message: str
    ai_generated: bool
    intent: str                          # answer | question | none
    extraction: ExtractedAnswer | None   # None when nothing was extracted
    accepted: bool | None                # None when nothing was submitted
    validation: ValidationResult | None  # verdict when something was submitted
    next_question: KYCField | None


# --------------------------------------------------------------------------- #
# Deterministic fallback phrasing, per language. help_text/examples come from
# the schema (English); the surrounding sentence is localized.
# --------------------------------------------------------------------------- #

_FB_ASK = {
    Language.ENGLISH: "Please tell me your {name}.",
    Language.HINGLISH: "Kripya apna {name} batayein.",
    Language.HINDI: "कृपया अपना {name} बताएं।",
}
_FB_ACK = {
    Language.ENGLISH: "Got it — {name} saved. ",
    Language.HINGLISH: "Theek hai — {name} save ho gaya. ",
    Language.HINDI: "ठीक है — {name} सेव हो गया। ",
}
_FB_CLARIFY = {
    Language.ENGLISH: "That answer for {name} didn't pass our check: {reason} {rule} Please try again.",
    Language.HINGLISH: "{name} ka yeh answer check me pass nahi hua: {reason} {rule} Dobara try karein.",
    Language.HINDI: "{name} का यह उत्तर जाँच में सही नहीं निकला: {reason} {rule} कृपया फिर से बताएं।",
}
_FB_COMPLETE = {
    Language.ENGLISH: "Wonderful — every required field is complete! Your KYC form is ready for the next step.",
    Language.HINGLISH: "Badhiya — saare required fields complete ho gaye! Aapka KYC form agle step ke liye ready hai.",
    Language.HINDI: "बहुत बढ़िया — सभी ज़रूरी फ़ील्ड पूरे हो गए! आपका केवाईसी फ़ॉर्म अगले चरण के लिए तैयार है।",
}
_FB_SUMMARY = {
    Language.ENGLISH: "You have completed {done} of {total} required fields ({pct}%). {left} to go — you're doing great!",
    Language.HINGLISH: "Aapne {total} me se {done} required fields complete kar liye hain ({pct}%). Bas {left} aur — badhiya chal raha hai!",
    Language.HINDI: "आपने {total} में से {done} ज़रूरी फ़ील्ड पूरे कर लिए हैं ({pct}%)। बस {left} और बाकी हैं — बहुत अच्छा!",
}
_FB_NO_ANSWER = {
    Language.ENGLISH: "Sorry, I couldn't find an answer in that. ",
    Language.HINGLISH: "Maaf kijiye, mujhe usme answer nahi mila. ",
    Language.HINDI: "माफ़ कीजिए, मुझे उसमें उत्तर नहीं मिला। ",
}

# Words a fallback extraction maps onto boolean yes/no.
_YES_WORDS = {"yes", "y", "haan", "han", "ha", "ji", "yes.", "haa", "हाँ", "हां", "जी"}
_NO_WORDS = {"no", "n", "nahi", "nahin", "na", "no.", "नहीं", "ना"}

# Ways people decline a question they cannot answer. Matched only when the
# CURRENT field is optional; a required field is never skipped by phrasing.
_SKIP_PHRASES = (
    "skip", "skip this", "skip it", "yes skip", "yes, skip", "please skip",
    "next", "next question", "pass", "leave it", "leave blank", "blank",
    "dont know", "don't know", "do not know", "no idea", "not sure",
    "not available", "na", "n/a", "none", "nothing", "i dont have",
    "i don't have", "dont have", "don't have", "not have", "no ckyc",
    "later", "maybe later", "cant remember", "can't remember",
    "pata nahi", "nahi hai", "nahi pata",
)


def _reads_as_skip(message: str) -> bool:
    """
    True when a reply is a refusal to answer rather than an answer.

    Matched on WHOLE WORDS against a short message. Substring matching was
    tried first and was wrong in a way that loses real data: "skipper street"
    contains "skip", so a genuine address would have been thrown away as a
    refusal. The length ceiling keeps "skip" a refusal while letting a longer
    sentence that merely mentions one be treated as an answer.
    """
    text = re.sub(r"[^a-z0-9\s'/]", " ", message.strip().lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return False
    if text in _SKIP_PHRASES:
        return True
    for phrase in _SKIP_PHRASES:
        if len(phrase) <= 3:
            continue  # "na", "n/a" only count as the WHOLE message, above
        # Whole-word/phrase hit, in a message short enough to be a refusal
        # rather than a value that happens to contain the word.
        if len(text) <= len(phrase) + 12 and re.search(
            rf"(?<!\w){re.escape(phrase)}(?!\w)", text
        ):
            return True
    return False


# Validation types whose values never contain meaningful spaces/dashes.
_COMPACT_TYPES = {
    ValidationType.PAN,
    ValidationType.AADHAAR,
    ValidationType.MOBILE,
    ValidationType.PINCODE,
}

# Fallback-extraction candidate patterns: lets the no-AI path spot a value
# inside a longer sentence ("mera pan hai abcde 1234 f"). Purely lexical —
# the Validation Engine still judges whatever is found.
_CANDIDATE_PATTERNS = {
    ValidationType.PAN: re.compile(
        r"[A-Za-z]{5}[\s-]*\d{4}[\s-]*[A-Za-z](?![A-Za-z0-9])"
    ),
    ValidationType.AADHAAR: re.compile(r"(?<!\d)\d(?:[\s-]*\d){11}(?!\d)"),
    ValidationType.MOBILE: re.compile(r"(?<!\d)[6-9](?:[\s-]*\d){9}(?!\d)"),
    ValidationType.PINCODE: re.compile(r"(?<!\d)\d{6}(?!\d)"),
    ValidationType.EMAIL: re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
}


class ConversationService:
    """AI-phrased conversation over the deterministic interview engine."""

    def __init__(
        self,
        interview: InterviewService,
        transcript: ConversationRepository,
        ai: AIService,
        prompts: PromptBuilder = prompt_builder,
        forms: FormService = form_service,
    ) -> None:
        self._interview = interview
        self._transcript = transcript
        self._ai = ai
        self._prompts = prompts
        self._forms = forms

    # ------------------------------------------------------------------ #
    # Public conversation operations
    # ------------------------------------------------------------------ #

    def start_conversation(self, language: Language) -> ConversationOpening:
        """Create a session and greet the user with the first phrased question."""
        session, question = self._interview.start_interview()
        message, ai_generated = self._phrase_question(session, question, language)
        self._remember(session.session_id, TurnRole.ASSISTANT, message)
        return ConversationOpening(
            session=session, question=question, message=message, ai_generated=ai_generated
        )

    def ask_next_question(
        self, session_id: str, language: Language
    ) -> tuple[Session, KYCField | None, str, bool]:
        """Phrase whatever the Session Engine says is next (or completion)."""
        session, question = self._interview.next_question(session_id)
        message, ai_generated = self._phrase_question(session, question, language)
        self._remember(session_id, TurnRole.ASSISTANT, message)
        return session, question, message, ai_generated

    def explain_field(
        self, session_id: str, field_id: str | None, language: Language
    ) -> FieldExplanation:
        """
        Explain a field in plain language. `field_id=None` means "the field
        currently being asked". Raises KYCFieldNotFoundError for unknown ids.
        """
        session, current = self._interview.next_question(session_id)
        field = self._forms.get_field(field_id) if field_id else current
        if field is None:
            # Interview complete and no explicit field — narrate that instead.
            summary = self.summarize_progress(session_id, language)
            self._remember(session_id, TurnRole.ASSISTANT, summary.message)
            return FieldExplanation(
                field=None, message=summary.message, ai_generated=summary.ai_generated
            )
        history = self._transcript.history(session_id)
        bundle = self._prompts.explain_field(field, history, language)
        message = self._ai_message(bundle)
        ai_generated = message is not None
        if message is None:
            message = self._fallback_explain(field, language)
        self._remember(session_id, TurnRole.ASSISTANT, message)
        return FieldExplanation(field=field, message=message, ai_generated=ai_generated)

    def extract_answer(
        self,
        session_id: str,
        message: str,
        field_id: str | None,
        language: Language,
    ) -> ExtractedAnswer:
        """
        Pull a normalized machine value out of a natural-language message for
        one field (default: the current field). Extraction ONLY — nothing is
        validated or stored here.
        """
        session, current = self._interview.next_question(session_id)
        field = self._forms.get_field(field_id) if field_id else current
        if field is None:
            # Interview complete: nothing left to extract into.
            return ExtractedAnswer(
                field_id="", value=None, confidence="low", intent="question",
                ai_generated=False,
            )
        history = self._transcript.history(session_id)
        bundle = self._prompts.extract_answer(field, message, history, language)
        try:
            payload = _ExtractionPayload(**self._ai.complete_json(bundle))
            # The AI never chooses the field — pin it to what WE asked about.
            return ExtractedAnswer(
                field_id=field.id,
                value=payload.value,
                confidence=payload.confidence,
                intent=payload.intent,
                ai_generated=True,
            )
        except (AIUnavailableError, ValidationError):
            return self._fallback_extract(field, message)

    def clarify_invalid_input(
        self,
        session_id: str,
        field: KYCField,
        rejected_value: str | None,
        validator_message: str,
        language: Language,
    ) -> tuple[str, bool]:
        """Phrase a gentle correction for an answer the validator rejected."""
        history = self._transcript.history(session_id)
        bundle = self._prompts.clarify_invalid_input(
            field, rejected_value, validator_message, history, language
        )
        message = self._ai_message(bundle)
        if message is not None:
            return message, True
        rule = VALIDATION_RULE_TEXT.get(field.validation_type, "")
        fallback = _FB_CLARIFY[language].format(
            name=field.display_name, reason=validator_message, rule=rule
        )
        if field.example:
            fallback += f" (Example: {field.example})"
        return fallback, False

    def summarize_progress(self, session_id: str, language: Language) -> ProgressSummary:
        """Narrate the deterministic progress report — numbers stay authoritative."""
        report = self._interview.current_progress(session_id)
        history = self._transcript.history(session_id)
        pending_names = tuple(
            self._forms.get_field(fid).display_name
            for fid in report.pending_required_fields
        )
        completed = not report.pending_required_fields
        bundle = self._prompts.summarize_progress(
            report.progress_percentage,
            report.completed_required_fields,
            report.required_fields,
            pending_names,
            completed,
            history,
            language,
        )
        message = self._ai_message(bundle)
        ai_generated = message is not None
        if message is None:
            if completed:
                message = _FB_COMPLETE[language]
            else:
                message = _FB_SUMMARY[language].format(
                    done=report.completed_required_fields,
                    total=report.required_fields,
                    pct=report.progress_percentage,
                    left=len(report.pending_required_fields),
                )
        return ProgressSummary(report=report, message=message, ai_generated=ai_generated)

    def reply(self, session_id: str, message: str, language: Language) -> ConversationReply:
        """
        Handle one user message end-to-end:

        1. remember the user's turn;
        2. AI extracts a machine value (fallback: heuristics);
        3. if the user asked a question -> explain the current field;
        4. otherwise submit through the Session Engine (sole validator);
        5. phrase the outcome: next question, completion, or gentle correction.
        """
        session, current = self._interview.next_question(session_id)
        self._remember(session_id, TurnRole.USER, message)

        if current is None:
            # Interview already complete — every message just gets the summary.
            summary = self.summarize_progress(session_id, language)
            self._remember(session_id, TurnRole.ASSISTANT, summary.message)
            return ConversationReply(
                session=session, message=summary.message,
                ai_generated=summary.ai_generated, intent="none", extraction=None,
                accepted=None, validation=None, next_question=None,
            )

        # A refusal is not an answer. Without this the value ('skip') either
        # failed validation and the same question came straight back, or was
        # stored as if it were the applicant's CKYC number.
        if not current.required and _reads_as_skip(message):
            session = self._interview.skip_field(session_id, current.id)
            following = self._interview.next_question(session_id)[1]
            if following is None:
                summary = self.summarize_progress(session_id, language)
                reply_text, ai_generated = summary.message, summary.ai_generated
            else:
                reply_text, ai_generated = self._phrase_question(
                    session, following, language
                )
            self._remember(session_id, TurnRole.ASSISTANT, reply_text)
            return ConversationReply(
                session=session, message=reply_text, ai_generated=ai_generated,
                intent="skip", extraction=None, accepted=None, validation=None,
                next_question=following,
            )

        extraction = self.extract_answer(session_id, message, None, language)

        if extraction.intent == "question":
            explanation = self.explain_field(session_id, current.id, language)
            return ConversationReply(
                session=session, message=explanation.message,
                ai_generated=explanation.ai_generated, intent="question",
                extraction=extraction, accepted=None, validation=None,
                next_question=current,
            )

        if extraction.value is None:
            # Nothing usable found — re-ask the same question.
            asked, ai_generated = self._phrase_question(session, current, language)
            reply_text = (
                asked if ai_generated else _FB_NO_ANSWER[language] + asked
            )
            self._remember(session_id, TurnRole.ASSISTANT, reply_text)
            return ConversationReply(
                session=session, message=reply_text, ai_generated=ai_generated,
                intent="answer", extraction=extraction, accepted=None,
                validation=None, next_question=current,
            )

        outcome = self._interview.submit_answer(session_id, current.id, extraction.value)

        if outcome.result.valid:
            if outcome.next_question is None:
                summary = self.summarize_progress(session_id, language)
                reply_text, ai_generated = summary.message, summary.ai_generated
            else:
                asked, ai_generated = self._phrase_question(
                    outcome.session, outcome.next_question, language
                )
                reply_text = (
                    asked
                    if ai_generated
                    else _FB_ACK[language].format(name=current.display_name) + asked
                )
        else:
            reply_text, ai_generated = self.clarify_invalid_input(
                session_id, current, extraction.value, outcome.result.message, language
            )

        self._remember(session_id, TurnRole.ASSISTANT, reply_text)
        return ConversationReply(
            session=outcome.session, message=reply_text, ai_generated=ai_generated,
            intent="answer", extraction=extraction, accepted=outcome.result.valid,
            validation=outcome.result, next_question=outcome.next_question,
        )

    def forget(self, session_id: str) -> None:
        """Drop a session's transcript (called when the session is deleted)."""
        self._transcript.delete(session_id)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _phrase_question(
        self, session: Session, question: KYCField | None, language: Language
    ) -> tuple[str, bool]:
        """Turn the engine-chosen question (or completion) into a message."""
        if question is None:
            summary = self.summarize_progress(session.session_id, language)
            return summary.message, summary.ai_generated
        report = self._interview.current_progress(session.session_id)
        history = self._transcript.history(session.session_id)
        bundle = self._prompts.ask_question(
            question,
            report.progress_percentage,
            report.completed_required_fields,
            report.required_fields,
            history,
            language,
        )
        message = self._ai_message(bundle)
        if message is not None:
            return message, True
        return self._fallback_ask(question, language), False

    def _ai_message(self, bundle: PromptBundle) -> str | None:
        """One-branch AI call: a message string, or None meaning 'fall back'."""
        try:
            return _MessagePayload(**self._ai.complete_json(bundle)).message
        except (AIUnavailableError, ValidationError):
            return None

    def _remember(self, session_id: str, role: TurnRole, content: str) -> None:
        self._transcript.append(
            session_id, ConversationTurn(role=role, content=content)
        )

    # --- deterministic fallback phrasing -------------------------------- #

    def _fallback_ask(self, field: KYCField, language: Language) -> str:
        parts = [_FB_ASK[language].format(name=field.display_name)]
        if field.help_text:
            parts.append(field.help_text)
        if field.example:
            parts.append(f"(Example: {field.example})")
        if field.options:
            options = ", ".join(option.label for option in field.options)
            parts.append(f"Options: {options}.")
        return " ".join(parts)

    def _fallback_explain(self, field: KYCField, language: Language) -> str:
        parts = [f"{field.display_name}:"]
        if field.help_text:
            parts.append(field.help_text)
        rule = VALIDATION_RULE_TEXT.get(field.validation_type)
        if rule and field.validation_type != ValidationType.NONE:
            parts.append(rule)
        if field.example:
            parts.append(f"Example: {field.example}.")
        if field.options:
            options = ", ".join(option.label for option in field.options)
            parts.append(f"You can choose from: {options}.")
        parts.append(_FB_ASK[language].format(name=field.display_name))
        return " ".join(parts)

    def _fallback_extract(self, field: KYCField, message: str) -> ExtractedAnswer:
        """
        No-AI extraction: conservative, deterministic heuristics. The
        Validation Engine remains the safety net for anything this gets wrong.
        """
        text = message.strip().strip('"').strip()
        if text.endswith("?"):
            return ExtractedAnswer(
                field_id=field.id, value=None, confidence="low",
                intent="question", ai_generated=False,
            )
        value = text
        pattern = _CANDIDATE_PATTERNS.get(field.validation_type)
        if pattern is not None:
            match = pattern.search(text)
            if match:
                value = match.group(0)
        if field.validation_type in _COMPACT_TYPES:
            value = value.replace(" ", "").replace("-", "")
            if field.validation_type == ValidationType.PAN:
                value = value.upper()
        if field.field_type == FieldType.BOOLEAN:
            lowered = value.lower()
            if lowered in _YES_WORDS:
                value = "yes"
            elif lowered in _NO_WORDS:
                value = "no"
        elif field.field_type == FieldType.MULTI_CHOICE and field.options:
            # "Salary and pension" -> "salary, pension". Longest labels first so
            # "Business Income" is not consumed by a bare "Income" match, and
            # only options the user actually named are recorded — never all of
            # them, and never a default.
            lowered = value.lower()
            chosen = [
                option.value
                for option in sorted(
                    field.options, key=lambda o: len(o.label), reverse=True
                )
                if option.label.lower() in lowered or option.value.lower() in lowered
            ]
            if chosen:
                order = [o.value for o in field.options]
                value = ", ".join(sorted(set(chosen), key=order.index))
        elif field.options:
            lowered = value.lower()
            for option in field.options:
                if lowered in (option.value.lower(), option.label.lower()):
                    value = option.value
                    break
        return ExtractedAnswer(
            field_id=field.id, value=value or None, confidence="medium",
            intent="answer", ai_generated=False,
        )
