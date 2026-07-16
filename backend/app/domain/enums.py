"""
Domain enumerations.

Central, strongly-typed vocabulary for the whole application. Every categorical
value a field can take (its input type, which validation rule applies, which
section it belongs to, its runtime status) is defined here exactly once, so no
other layer ever compares against magic strings.

All enums inherit from `str` so they serialize cleanly to JSON in API responses
and read naturally in logs (e.g. "text" instead of "FieldType.TEXT").
"""

from enum import Enum


class FieldType(str, Enum):
    """
    The kind of input a field expects — drives how the frontend renders it and
    how later phases (interview, PDF overlay) treat the value.
    """

    TEXT = "text"              # free single-line text (names, addresses)
    NUMBER = "number"          # numeric value (income amount)
    DATE = "date"              # calendar date (DOB)
    EMAIL = "email"            # email address
    PHONE = "phone"            # telephone / mobile number
    SINGLE_CHOICE = "single_choice"  # pick exactly one option (gender, income band)
    MULTI_CHOICE = "multi_choice"    # pick one or more options (proof documents)
    BOOLEAN = "boolean"        # yes/no or a single tick (PEP declaration)


class ValidationType(str, Enum):
    """
    Which deterministic validation rule applies to a field's value.

    These are declarations only — the actual rule implementations arrive in
    Phase 4 (`domain/validators`). NONE means "no special rule beyond type".
    """

    NONE = "none"
    PAN = "pan"                # Indian PAN: 5 letters, 4 digits, 1 letter
    AADHAAR = "aadhaar"        # 12-digit UID (Verhoeff checksum)
    MOBILE = "mobile"          # 10-digit Indian mobile
    EMAIL = "email"            # RFC-style email
    PINCODE = "pincode"        # 6-digit postal code
    DATE = "date"              # parseable, sane calendar date (not in the future)
    DOB = "dob"                # date of birth: valid date, past, realistic age
    NAME = "name"              # non-empty alphabetic name
    NUMBER = "number"          # non-negative numeric amount


class SectionType(str, Enum):
    """
    The top-level sections of the CVL Individual KYC form, matching the printed
    layout of the source document (A / B / C + Declaration).
    """

    IDENTITY = "identity_details"        # Section A — Identity Details
    ADDRESS = "address_details"          # Section B — Address Details
    OTHER = "other_details"              # Section C — Other Details (income, occupation, PEP)
    DECLARATION = "declaration"          # Declaration & signature


class FieldStatus(str, Enum):
    """
    Runtime status of a single field within an interview session.

    Not used by the static schema itself, but defined here so Phase 5's session
    state and this schema share one vocabulary.
    """

    PENDING = "pending"        # not yet asked / not answered
    ANSWERED = "answered"      # user provided a value, not yet validated
    VALID = "valid"            # value passed validation
    INVALID = "invalid"        # value failed validation
    SKIPPED = "skipped"        # optional field explicitly skipped


class InterviewStatus(str, Enum):
    """Overall lifecycle status of an interview session (used from Phase 5)."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"       # all required fields valid
    ABANDONED = "abandoned"


class Language(str, Enum):
    """
    Languages the AI conversation layer can speak (Phase 5).

    The language ONLY changes how replies are phrased — field ids, stored
    answers, and validation stay language-independent machine values.
    """

    ENGLISH = "english"
    HINGLISH = "hinglish"    # Hindi in Roman script, mixed naturally with English
    HINDI = "hindi"          # simple Hindi, Devanagari script


class DocumentCategory(str, Enum):
    """
    Broad category of an uploaded document (Phase 6) — decides which storage
    subdirectory a file lands in and how later phases (OCR) will treat it.
    """

    PDF = "pdf"        # stored under uploads/pdf/
    IMAGE = "image"    # stored under uploads/images/


class DocumentQuality(str, Enum):
    """
    Estimated scan/photo quality of an uploaded document (Phase 7).

    Drives user-facing warnings ("your scan looks blurry") and lets the
    pipeline handle poor scans and blank pages gracefully instead of failing.
    """

    GOOD = "good"      # digital PDF or sharp, high-resolution scan
    FAIR = "fair"      # readable but OCR accuracy may drop
    POOR = "poor"      # low resolution / low contrast — expect OCR mistakes
    BLANK = "blank"    # page appears to contain (almost) nothing


class ExtractionSource(str, Enum):
    """
    Where an extracted field's text originally came from (Phase 7).

    A digital PDF's embedded text layer is exact (no OCR noise), while OCR of
    a scanned image is probabilistic — the ConfidenceEngine weighs the two very
    differently.
    """

    PDF_TEXT_LAYER = "pdf_text_layer"   # exact text embedded in the PDF
    OCR = "ocr"                         # recognized from pixels by the OCR engine


class ExtractionMethod(str, Enum):
    """
    HOW the ExtractionEngine matched a value to a KYC field (Phase 7).

    Reported per field for transparency and used by the ConfidenceEngine:
    an unambiguous format pattern (e.g. a PAN) is stronger evidence than a
    label match, which is stronger than spotting a bare option word.
    """

    LABEL = "label_match"       # "PAN : ABCDE1234F" — value found after the field's label
    PATTERN = "pattern_match"   # value matched an unambiguous format (PAN, Aadhaar, email…)
    OPTION = "option_match"     # a schema option word found on the field's labelled line
