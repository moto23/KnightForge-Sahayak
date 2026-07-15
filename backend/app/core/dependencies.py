"""
Shared FastAPI dependency providers.

Central place where routes obtain their collaborators via `Depends()`. Routes
never construct services themselves — they declare what they need and this
module provides it, which keeps wiring in one spot and makes overriding
dependencies in tests trivial (app.dependency_overrides).
"""

from app.services.form_service import FormService, form_service
from app.services.form_validation_service import (
    FormValidationService,
    form_validation_service,
)


def get_form_service() -> FormService:
    """Provide the shared, stateless FormService instance."""
    return form_service


def get_form_validation_service() -> FormValidationService:
    """Provide the shared, stateless FormValidationService instance."""
    return form_validation_service
