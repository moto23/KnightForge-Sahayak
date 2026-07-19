"""
Deterministic validation rules.

Each public function validates ONE string value against ONE rule and returns a
ValidationResult. They are pure (no I/O, no globals, no AI), so every function
is directly unit-testable: call it with a string, assert on the result.

Conventions:
  * Input is always the raw user string. Validators trim surrounding whitespace
    but do not otherwise mutate global state.
  * An empty value is treated as "nothing to validate" and PASSES here — the
    required/empty rule is a separate concern handled by `validate_required`
    and by the engine (which checks required-ness before format).
"""

import re
from datetime import date, datetime

from app.domain.validators.result import ValidationResult

# --------------------------------------------------------------------------- #
# Compiled patterns (module-level so they compile once).
# --------------------------------------------------------------------------- #

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_AADHAAR_RE = re.compile(r"^[0-9]{12}$")
_MOBILE_RE = re.compile(r"^[6-9][0-9]{9}$")           # Indian mobiles start 6-9
_PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")          # 6 digits, no leading zero
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]*$")     # letters + common name punctuation

# Accepted date input formats (day-first, matching the KYC form).
_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d")

_MAX_HUMAN_AGE = 120


def _clean(value: str) -> str:
    """Trim surrounding whitespace; treat None-ish input as empty string."""
    return (value or "").strip()


def _parse_date(value: str) -> date | None:
    """Try each accepted format; return a date or None if unparseable."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Verhoeff checksum — the real algorithm the UIDAI uses for Aadhaar.
# Deterministic table lookup; no external dependency.
# --------------------------------------------------------------------------- #

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def _verhoeff_valid(number: str) -> bool:
    """Return True if `number` (a digit string) passes the Verhoeff checksum."""
    check = 0
    for i, digit in enumerate(reversed(number)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[i % 8][int(digit)]]
    return check == 0


# --------------------------------------------------------------------------- #
# Public validators — one per rule.
# --------------------------------------------------------------------------- #


def validate_required(value: str) -> ValidationResult:
    """Pass if the value is present and non-blank."""
    if _clean(value):
        return ValidationResult.ok("Value is present.")
    return ValidationResult.fail("required", "This field is required.")


def validate_pan(value: str) -> ValidationResult:
    """PAN: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F). Case-insensitive."""
    v = _clean(value).upper()
    if not v:
        return ValidationResult.ok("No PAN provided.")
    if _PAN_RE.match(v):
        return ValidationResult.ok("PAN is valid.", code="valid_pan")
    return ValidationResult.fail(
        "invalid_pan", "PAN format is invalid. Expected 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)."
    )


def validate_aadhaar(value: str) -> ValidationResult:
    """Aadhaar: exactly 12 digits AND a valid Verhoeff checksum."""
    v = _clean(value).replace(" ", "")
    if not v:
        return ValidationResult.ok("No Aadhaar provided.")
    if not _AADHAAR_RE.match(v):
        return ValidationResult.fail(
            "invalid_aadhaar", "Aadhaar must be exactly 12 digits."
        )
    if not _verhoeff_valid(v):
        return ValidationResult.fail(
            "invalid_aadhaar_checksum", "Aadhaar number failed its checksum — please re-check the digits."
        )
    return ValidationResult.ok("Aadhaar is valid.", code="valid_aadhaar")


def validate_mobile(value: str) -> ValidationResult:
    """Mobile: 10 digits starting 6-9 (Indian). Strips +91 / 0 prefixes."""
    v = _clean(value).replace(" ", "").replace("-", "")
    if not v:
        return ValidationResult.ok("No mobile number provided.")
    if v.startswith("+91"):
        v = v[3:]
    elif v.startswith("91") and len(v) == 12:
        v = v[2:]
    elif v.startswith("0") and len(v) == 11:
        v = v[1:]
    if _MOBILE_RE.match(v):
        return ValidationResult.ok("Mobile number is valid.", code="valid_mobile")
    return ValidationResult.fail(
        "invalid_mobile", "Mobile number must be 10 digits and start with 6, 7, 8, or 9."
    )


def validate_email(value: str) -> ValidationResult:
    """Email: a single local@domain.tld shape (deterministic, not RFC-exhaustive)."""
    v = _clean(value)
    if not v:
        return ValidationResult.ok("No email provided.")
    if _EMAIL_RE.match(v):
        return ValidationResult.ok("Email is valid.", code="valid_email")
    return ValidationResult.fail("invalid_email", "Email address format is invalid.")


def validate_pincode(value: str) -> ValidationResult:
    """PIN code: 6 digits, first digit 1-9 (Indian postal code)."""
    v = _clean(value)
    if not v:
        return ValidationResult.ok("No PIN code provided.")
    if _PINCODE_RE.match(v):
        return ValidationResult.ok("PIN code is valid.", code="valid_pincode")
    return ValidationResult.fail(
        "invalid_pincode", "PIN code must be 6 digits and cannot start with 0."
    )


def validate_name(value: str) -> ValidationResult:
    """Name: starts with a letter, contains only letters, spaces, . ' - characters."""
    v = _clean(value)
    if not v:
        return ValidationResult.ok("No name provided.")
    if len(v) < 2:
        return ValidationResult.fail("invalid_name", "Name is too short.")
    if _NAME_RE.match(v):
        return ValidationResult.ok("Name is valid.", code="valid_name")
    return ValidationResult.fail(
        "invalid_name", "Name may only contain letters, spaces, and . ' - characters."
    )


# Answers that are grammatically a "name" but cannot be a place. A declaration
# Place reading "Yes" is what prompted this: the printed form has a YES/NO row
# a few lines above, and an affirmative reply is close enough to a word that
# every letters-only rule accepted it.
_NOT_A_PLACE = {
    "yes", "no", "y", "n", "true", "false", "ok", "okay", "none", "nil",
    "na", "n/a", "not applicable", "same", "same as above", "above",
}


def validate_place(value: str) -> ValidationResult:
    """A town/city name: a real word, never a yes/no answer."""
    v = _clean(value)
    if not v:
        return ValidationResult.ok("No place provided.")
    if v.lower() in _NOT_A_PLACE:
        return ValidationResult.fail(
            "invalid_place",
            "That looks like an answer to a different question. "
            "Please give the city or town where you are signing.",
        )
    if len(v) < 3:
        return ValidationResult.fail("invalid_place", "Place name is too short.")
    if _NAME_RE.match(v):
        return ValidationResult.ok("Place is valid.", code="valid_place")
    return ValidationResult.fail(
        "invalid_place",
        "Place may only contain letters, spaces, and . ' - characters.",
    )


def validate_date(value: str) -> ValidationResult:
    """A parseable calendar date (DD-MM-YYYY preferred) that is not in the future."""
    v = _clean(value)
    if not v:
        return ValidationResult.ok("No date provided.")
    parsed = _parse_date(v)
    if parsed is None:
        return ValidationResult.fail(
            "invalid_date", "Date is invalid. Use DD-MM-YYYY (e.g. 15-08-1999)."
        )
    if parsed > date.today():
        return ValidationResult.fail("invalid_date", "Date cannot be in the future.")
    return ValidationResult.ok("Date is valid.", code="valid_date")


def validate_dob(value: str) -> ValidationResult:
    """Date of birth: a valid past date yielding a realistic age (0-120 years)."""
    v = _clean(value)
    if not v:
        return ValidationResult.ok("No date of birth provided.")
    parsed = _parse_date(v)
    if parsed is None:
        return ValidationResult.fail(
            "invalid_dob", "Date of birth is invalid. Use DD-MM-YYYY (e.g. 15-08-1999)."
        )
    today = date.today()
    if parsed >= today:
        return ValidationResult.fail(
            "invalid_dob", "Date of birth must be in the past."
        )
    age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))
    if age > _MAX_HUMAN_AGE:
        return ValidationResult.fail(
            "invalid_dob", f"Date of birth implies an unrealistic age (> {_MAX_HUMAN_AGE})."
        )
    return ValidationResult.ok("Date of birth is valid.", code="valid_dob")


def validate_number(value: str) -> ValidationResult:
    """A non-negative number (integer or decimal). Allows thousands separators."""
    v = _clean(value).replace(",", "")
    if not v:
        return ValidationResult.ok("No number provided.")
    try:
        number = float(v)
    except ValueError:
        return ValidationResult.fail("invalid_number", "Value must be a number.")
    if number < 0:
        return ValidationResult.fail("invalid_number", "Value cannot be negative.")
    return ValidationResult.ok("Number is valid.", code="valid_number")


def validate_noop(value: str) -> ValidationResult:
    """Pass-through for fields with no special rule (ValidationType.NONE)."""
    return ValidationResult.ok("No validation rule for this field.", code="valid")
