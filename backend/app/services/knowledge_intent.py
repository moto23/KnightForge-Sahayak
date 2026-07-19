"""
Knowledge Chat intent routing.

Not every question belongs in the RAG engine. "Hi" and "Who are you?" have no
answer in the KYC corpus, so routing them through retrieval produced an
"I don't know" for perfectly reasonable conversation. Equally, "Who is Virat
Kohli?" must NOT be answered from the model's general knowledge — this
assistant only speaks for what is actually indexed.

Four intents, decided before retrieval:

    CONVERSATIONAL — greetings, identity, capabilities: answered as Sahayak
    DATETIME       — answered deterministically from server time
    KYC            — the domain: retrieval + grounded generation + citations
    OUT_OF_DOMAIN  — clearly unrelated: a scoped refusal, no generation

Deliberately deterministic (no model call): routing must be instant, free and
identical every time. KYC is the default — anything not confidently matched as
one of the other three still goes through retrieval, where the existing
relevance gate remains the real gatekeeper.
"""

import re
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo


class QueryIntent(str, Enum):
    """What kind of question the user just asked."""

    CONVERSATIONAL = "conversational"
    DATETIME = "datetime"
    KYC = "kyc"
    WORKFLOW = "workflow"   # about THIS user's session, not KYC in general
    OUT_OF_DOMAIN = "out_of_domain"


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

# Domain terms. Any of these makes the question the RAG engine's business,
# and they win over every other rule below.
_DOMAIN = re.compile(
    r"\b(kyc|kra|ckyc|re-?kyc|pan|aadhaar|aadhar|uid|passport|voter|epic|"
    r"driving\s*licen[cs]e|dl|ration|utility\s*bill|electricity\s*bill|"
    r"bank\s*statement|passbook|ifsc|address\s*proof|identity\s*proof|poi|poa|"
    r"proof\s+of\s+(identity|address)|document|form|cvl|cdsl|sbi|hdfc|icici|"
    r"axis|nominee|declaration|pep|politically\s+exposed|nri|resident|"
    r"occupation|income|annual\s+income|net\s*worth|marital|gender|"
    r"date\s+of\s+birth|dob|nationality|pin\s*code|pincode|signature|"
    r"attest|verification|ipv|in-?person|intermediary|applicant|"
    r"minor|guardian|age|eligib|mandatory|required|submit|upload|extract|"
    r"interview|progress|prefill|profile|generate\s+pdf|fill)\b",
    re.I,
)

# Greetings and small talk.
_GREETING = re.compile(
    r"^\s*(hi|hii+|hey+|hello+|yo|namaste|hola|good\s+(morning|afternoon|"
    r"evening|day)|thanks|thank\s+you|thx|ok(ay)?|cool|nice|great|bye|"
    r"goodbye|see\s+you)\b[\s!.?]*$",
    re.I,
)

# Questions about the assistant or the platform itself.
_ABOUT_SELF = re.compile(
    r"\b(who\s+(are|r)\s+(you|u)|what\s+are\s+you|who\s+(made|built|created|"
    r"developed)\s+(you|this)|your\s+name|what\s+(is|are)\s+(this|sahayak|"
    r"knightforge)|what\s+(can|do)\s+you\s+do|how\s+can\s+you\s+help|"
    r"help\s+me\s+with|what\s+should\s+i\s+do|how\s+(do|does)\s+(this|it)\s+work|"
    r"how\s+are\s+you|what\s+is\s+this\s+(platform|app|site|tool)|"
    r"capabilit|feature)\b",
    re.I,
)

# Date / time questions.
_DATETIME = re.compile(
    r"\b(today'?s?\s+date|what\s+(is\s+)?(the\s+)?(date|time)|current\s+"
    r"(date|time)|what\s+day\s+is|right\s+now|date\s+today|time\s+now)\b",
    re.I,
)

# Topics that are clearly somebody else's job. Only consulted when NO domain
# term is present, so "Is PAN required?" can never land here.
_OFF_TOPIC = re.compile(
    r"\b(cricket|football|kohli|sachin|movie|film|song|music|recipe|cook|"
    r"weather|joke|poem|story|quantum|physics|chemistry|biology|astronomy|"
    r"planet|football|nba|ipl|election|president|prime\s+minister|capital\s+of|"
    r"translate|code|python|javascript|stock\s+price|crypto|bitcoin|"
    r"who\s+is\s+[a-z]|what\s+is\s+a\s+(ball|car|dog|cat|tree))\b",
    re.I,
)


# Questions about the user's OWN session rather than KYC in general. These
# mention domain words ("photo", "PAN", "fields"), so without this they were
# classified KYC and sent to retrieval — which can only answer from official
# documents and knows nothing about this applicant. The honest answer lives in
# the session, so it is read from there instead of being generated.
_WORKFLOW = re.compile(
    r"\b("
    r"my\s+(progress|status|form|application|details|answers?|fields?|photo|"
    r"signature|document|documents|profile)"
    r"|(what|how\s+much)\s+(is\s+)?(left|remaining|remains|pending)"
    r"|what(\s+is|'?s)?\s+remaining"
    r"|(fields?|questions?|anything)\s+(are\s+)?(still\s+)?(missing|left|pending|remaining)"
    r"|(missing|remaining|pending)\s+fields?"
    r"|what\s+(should|do)\s+i\s+(answer|fill|do)\s*(next)?"
    r"|next\s+question"
    r"|(have|did)\s+i\s+(uploaded?|given|answered|filled)"
    r"|is\s+my\s+\w+\s+(uploaded?|done|complete|filled)"
    r"|am\s+i\s+(done|finished|complete)"
    r"|how\s+far\s+(am\s+i|along)"
    r")\b",
    re.I,
)

# Questions about the product itself. They name Sahayak or ask how "this"
# works, which is neither small talk nor something the KYC corpus documents.
_ABOUT_PLATFORM = re.compile(
    r"\b(sahayak|this\s+(app|tool|site|platform|assistant)|"
    r"how\s+(does|do)\s+(this|it|sahayak)\s+work)\b",
    re.I,
)


def classify_intent(question: str) -> QueryIntent:
    """Route one question. Deterministic, no model call."""
    text = (question or "").strip()
    if not text:
        return QueryIntent.CONVERSATIONAL

    # Domain vocabulary always wins: a KYC question that happens to say
    # "hi there, is PAN required?" is a KYC question.
    has_domain = bool(_DOMAIN.search(text))

    if _DATETIME.search(text) and not has_domain:
        return QueryIntent.DATETIME
    # Checked BEFORE the domain rule: 'is my photo uploaded?' contains a
    # domain word but is a question about this session, not about KYC.
    if _WORKFLOW.search(text):
        return QueryIntent.WORKFLOW
    if _ABOUT_PLATFORM.search(text):
        return QueryIntent.CONVERSATIONAL
    if has_domain:
        return QueryIntent.KYC
    if _GREETING.match(text) or _ABOUT_SELF.search(text):
        return QueryIntent.CONVERSATIONAL
    if _OFF_TOPIC.search(text):
        return QueryIntent.OUT_OF_DOMAIN
    # Unknown: let retrieval + the relevance gate decide. They already refuse
    # anything the corpus cannot support, so this stays safe.
    return QueryIntent.KYC


# --------------------------------------------------------------------------- #
# Deterministic answers
# --------------------------------------------------------------------------- #

_IDENTITY = (
    "I'm Sahayak, the AI paperwork assistant inside KnightForge Sahayak. "
    "I help you complete KYC paperwork end to end."
)

_CAPABILITIES = (
    "Here's what I can do:\n\n"
    "• **Read your documents** — upload a KYC form plus supporting proofs "
    "(PAN, Aadhaar, passport, driving licence, bank statement, utility bill, "
    "voter ID and more). I detect each document type automatically and "
    "extract its fields.\n"
    "• **Build one profile** — everything extracted is merged into a single "
    "verified profile, with conflicts flagged for you to resolve.\n"
    "• **Interview you for the gaps** — I only ask for the fields your chosen "
    "form still needs, so nothing already on your documents is asked twice.\n"
    "• **Track progress** — you can see every field, where its value came "
    "from and what is still outstanding.\n"
    "• **Generate your completed PDF** — filled onto the form you uploaded, "
    "with earlier versions kept in history.\n"
    "• **Answer KYC questions** — grounded in the official documents I have "
    "indexed, always with citations.\n\n"
    "Ask me something like \"Which documents are required?\" or "
    "\"What is accepted as address proof?\""
)


def conversational_answer(question: str) -> str:
    """A natural reply as Sahayak — never routed through retrieval."""
    text = (question or "").strip()

    if re.search(r"\bhow\s+are\s+you\b", text, re.I):
        return (
            f"I'm doing well, thank you. {_IDENTITY}\n\n"
            "What would you like help with — your documents, your form, or a "
            "KYC question?"
        )
    if re.search(r"\bwho\s+(made|built|created|developed)\b", text, re.I):
        return (
            "I was built by the KnightForge team as the assistant inside "
            "KnightForge Sahayak. I run on this platform's own document "
            "pipeline and a knowledge base of official KYC documents, so my "
            "answers stay grounded in indexed sources rather than guesswork."
        )
    if re.search(
        r"\b(what\s+(can|do)\s+you\s+do|how\s+can\s+you\s+help|capabilit|"
        r"feature|what\s+should\s+i\s+do|help\s+me\s+with|"
        r"what\s+is\s+this\s+(platform|app|site|tool)|"
        r"how\s+(do|does)\s+(this|it)\s+work)\b",
        text,
        re.I,
    ):
        return f"{_IDENTITY}\n\n{_CAPABILITIES}"
    if re.search(r"\b(who|what)\s+(are|r|is)\s+(you|u|this|sahayak|knightforge)\b", text, re.I):
        return f"{_IDENTITY}\n\n{_CAPABILITIES}"
    if re.match(r"^\s*(thanks|thank\s+you|thx)\b", text, re.I):
        return "You're welcome. Ask me anything else about your KYC paperwork."
    if re.match(r"^\s*(bye|goodbye|see\s+you)\b", text, re.I):
        return "Goodbye — your progress is saved, so you can pick up any time."
    # Plain greeting.
    return (
        f"Hello! {_IDENTITY}\n\n"
        "I can read your uploaded documents, fill in what they prove, ask you "
        "only for what's missing, and generate your completed form. I can also "
        "answer KYC questions from the official documents I have indexed.\n\n"
        "What would you like to do?"
    )


def datetime_answer(question: str, tz_name: str) -> str:
    """
    Answer date/time from the server clock, naming the timezone explicitly.

    The user's own timezone is never guessed — the server's configured zone is
    stated so the answer is unambiguous.
    """
    try:
        now = datetime.now(ZoneInfo(tz_name))
        zone = tz_name
    except Exception:  # noqa: BLE001 - bad/unavailable zone: fall back to local
        now = datetime.now().astimezone()
        zone = str(now.tzinfo)

    asked_time = bool(re.search(r"\btime\b", question or "", re.I))
    date_text = now.strftime("%A, %d %B %Y")
    if asked_time:
        return (
            f"It's {now.strftime('%H:%M')} on {date_text} ({zone}, server time)."
        )
    return f"Today is {date_text} ({zone}, server time)."
