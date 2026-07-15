"""
ValidationResult — the single, strongly-typed outcome of every validation.

Every validator in this package returns exactly this model, so callers (the
engine, services, API responses) handle one uniform shape whether the rule was
a PAN checksum or a required-field check.

`code` values are stable machine-readable identifiers (e.g. "invalid_pan") that
clients and the future interview engine can branch on; `message` is the
human-readable explanation shown to users.
"""

from pydantic import BaseModel, ConfigDict, Field


class ValidationResult(BaseModel):
    """Outcome of validating one value against one rule."""

    model_config = ConfigDict(frozen=True)

    valid: bool = Field(..., description="True if the value passed the rule.")
    code: str = Field(..., description="Stable machine-readable result code.")
    message: str = Field(..., description="Human-readable explanation.")

    @classmethod
    def ok(cls, message: str, code: str = "valid") -> "ValidationResult":
        """Convenience constructor for a passing result."""
        return cls(valid=True, code=code, message=message)

    @classmethod
    def fail(cls, code: str, message: str) -> "ValidationResult":
        """Convenience constructor for a failing result."""
        return cls(valid=False, code=code, message=message)
