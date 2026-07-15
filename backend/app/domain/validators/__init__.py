# `domain.validators` package: deterministic validation of KYC field values.
#
# Everything here is pure Python — no I/O, no AI, no HTTP. Each rule is a small
# unit-testable function; the ValidationEngine dispatches to them based on the
# field's declared `validation_type` in the KYC schema registry.

from app.domain.validators.engine import ValidationEngine, validation_engine
from app.domain.validators.result import ValidationResult

__all__ = ["ValidationEngine", "ValidationResult", "validation_engine"]
