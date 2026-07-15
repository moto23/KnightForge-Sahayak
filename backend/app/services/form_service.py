"""
FormService — business-layer access to the KYC form schema.

Wraps the KYC schema registry with the operations the application needs, so
routes and future services (interview, validation, PDF) depend on this service
rather than reaching into the registry or domain internals directly.

It holds no state and performs no I/O — it's a thin, testable orchestration
layer over the immutable registry. A `KYCFieldNotFoundError` is raised (not an
HTTP error) when a field id is unknown, keeping this layer HTTP-agnostic.
"""

from app.core.exceptions import KYCFieldNotFoundError
from app.domain.enums import SectionType
from app.domain.kyc_schema import KYCSchemaRegistry, kyc_registry
from app.domain.models import KYCField, KYCForm, KYCSection


class FormService:
    """Use-case operations over the KYC form definition."""

    def __init__(self, registry: KYCSchemaRegistry = kyc_registry) -> None:
        # Registry is injected (defaulting to the singleton) so tests can pass a
        # custom form definition without touching global state.
        self._registry = registry

    def get_form(self) -> KYCForm:
        """Return the complete form definition (metadata + sections + fields)."""
        return self._registry.form

    def get_all_fields(self) -> tuple[KYCField, ...]:
        """Return every field on the form, in form order."""
        return self._registry.all_fields()

    def get_sections(self) -> tuple[KYCSection, ...]:
        """Return all sections in display order."""
        return self._registry.sections

    def get_field(self, field_id: str) -> KYCField:
        """
        Return a single field by id.

        Raises KYCFieldNotFoundError if the id is unknown, so callers get a
        typed domain error rather than a None they might forget to check.
        """
        field = self._registry.get_field(field_id)
        if field is None:
            raise KYCFieldNotFoundError(field_id)
        return field

    def get_required_fields(self) -> tuple[KYCField, ...]:
        """Return only the mandatory fields, in form order."""
        return self._registry.required_fields()

    def get_fields_by_section(self, section: SectionType) -> tuple[KYCField, ...]:
        """Return all fields belonging to the given section."""
        return self._registry.fields_by_section(section)


# Stateless singleton — safe to share across requests.
form_service = FormService()
