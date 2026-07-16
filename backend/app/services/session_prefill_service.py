"""
SessionPrefillService — pour trusted extracted values into an interview.

Final stage of the Phase 7 pipeline (requirement 8). Takes an ExtractionResult
and an existing interview session and writes ONLY the fields the pipeline
marked `accepted` (valid + high-confidence). Everything else is deliberately
left unanswered so the deterministic interview asks about it — an uncertain
OCR guess must never silently become a user's official KYC answer.

Every write goes through SessionService.update_answer, i.e. through the
Validation Engine AGAIN — prefilled values obey exactly the same rules as
typed ones, and session progress/next-question state refreshes for free.
"""

import logging

from app.domain.extraction import (
    ExtractionResult,
    PrefilledField,
    PrefillReport,
    SkippedField,
)
from app.services.form_service import FormService, form_service
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)


class SessionPrefillService:
    """Apply high-confidence extracted fields to an existing interview session."""

    def __init__(self, sessions: SessionService, forms: FormService = form_service) -> None:
        self._sessions = sessions
        self._forms = forms

    def prefill(
        self, session_id: str, extraction: ExtractionResult, overwrite: bool = False
    ) -> PrefillReport:
        """
        Write accepted fields into the session; report everything else.

        Skip reasons (each extracted-but-not-written field gets exactly one):
          low_confidence   — scored below the prefill threshold
          invalid_value    — the Validation Engine rejected the value
          already_answered — the user answered it first and overwrite=False
                             (a human answer outranks a machine guess)

        Raises SessionNotFoundError (404) for an unknown session.
        """
        session = self._sessions.get_session(session_id)  # 404 fast, before writes

        prefilled: list[PrefilledField] = []
        skipped: list[SkippedField] = []

        for field in extraction.fields:
            if not field.validation_result.valid:
                skipped.append(
                    SkippedField(
                        field_id=field.field_id,
                        reason="invalid_value",
                        confidence=field.confidence,
                    )
                )
                continue
            if not field.accepted:
                skipped.append(
                    SkippedField(
                        field_id=field.field_id,
                        reason="low_confidence",
                        confidence=field.confidence,
                    )
                )
                continue
            if field.field_id in session.answers and not overwrite:
                skipped.append(
                    SkippedField(
                        field_id=field.field_id,
                        reason="already_answered",
                        confidence=field.confidence,
                    )
                )
                continue

            # Through the normal answer path: validated again, derived session
            # state (progress, next question, status) refreshed automatically.
            session, result = self._sessions.update_answer(
                session_id, field.field_id, field.value
            )
            if result.valid:
                prefilled.append(
                    PrefilledField(
                        field_id=field.field_id,
                        value=field.value,
                        confidence=field.confidence,
                    )
                )
            else:  # defense in depth — should be unreachable given `accepted`
                skipped.append(
                    SkippedField(
                        field_id=field.field_id,
                        reason="invalid_value",
                        confidence=field.confidence,
                    )
                )

        remaining = tuple(
            fid for fid in self._required_ids() if fid not in session.answers
        )
        logger.info(
            "Prefill for session %s from %s: %d written, %d skipped, %d required remaining",
            session_id, extraction.document_id, len(prefilled), len(skipped), len(remaining),
        )
        return PrefillReport(
            session_id=session_id,
            document_id=extraction.document_id,
            prefilled=tuple(prefilled),
            skipped=tuple(skipped),
            remaining_required=remaining,
            progress_percentage=session.progress_percentage,
        )

    def _required_ids(self) -> tuple[str, ...]:
        """Required field ids in form order (schema-driven, never hardcoded)."""
        return tuple(f.id for f in self._forms.get_required_fields())
