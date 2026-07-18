"""
DocumentIntelligenceService (Phase 11) — the Universal Document Intelligence
pipeline orchestrator.

Composes the schema-driven flow around the UNTOUCHED existing machinery:

    Upload -> DocumentUnderstandingService (analysis + OCR, cached)
           -> DocumentClassifierService   (which schema?)
           -> FieldMapper                 (ONE extract_document(schema))
           -> MergeService                (unified canonical profile)
           -> ConflictService             (disagreements, never overwritten)
           -> SessionService.update_answer (validation runs after merging)
           -> Interview asks only what's missing -> existing PDF engine

This service owns only sequencing and per-session state. Every value written
into the interview session goes through the normal answer path (validated
again by the deterministic engine), and the service tracks exactly which
answers it wrote — so it can update or retract them when documents change,
while NEVER touching an answer the user typed themselves.
"""

import logging

from app.core.config import settings
from app.core.exceptions import (
    DocumentNotFoundError,
    DocumentSchemasMissingError,
    InvalidPrimaryFormError,
)
from app.domain.intelligence import (
    AppliedAnswer,
    DocumentProfile,
    DocumentSchema,
    FieldConflict,
    MergedField,
    ProfileRepository,
    ProfileState,
    SchemaSource,
)
from app.domain.canonical_schema import CanonicalSchemaRegistry, canonical_registry
from app.domain.session import Session, utc_now
from app.domain.intelligence import CanonicalValue, ExtraValue
from app.services.conflict_service import ConflictService
from app.services.document_classifier import DocumentClassifierService
from app.services.document_understanding_service import DocumentUnderstandingService
from app.services.field_mapper import FieldMapper
from app.services.merge_service import MergeService
from app.services.semantic_extractor import SemanticExtractorService
from app.services.session_service import SessionService
from app.services.upload_service import UploadService

logger = logging.getLogger(__name__)


def _combine_canonical(
    deterministic: tuple[CanonicalValue, ...], semantic: tuple[CanonicalValue, ...]
) -> tuple[CanonicalValue, ...]:
    """
    Merge the two extraction passes per canonical field: a validated value
    beats an unvalidated one, then higher confidence wins; the deterministic
    pass wins exact ties (it is reproducible).
    """
    best: dict[str, CanonicalValue] = {v.canonical_id: v for v in deterministic}
    for candidate in semantic:
        current = best.get(candidate.canonical_id)
        if current is None:
            best[candidate.canonical_id] = candidate
            continue
        if (candidate.valid, candidate.confidence) > (current.valid, current.confidence):
            best[candidate.canonical_id] = candidate
    return tuple(best.values())


def _combine_extras(
    deterministic: tuple[ExtraValue, ...], semantic: tuple[ExtraValue, ...]
) -> tuple[ExtraValue, ...]:
    """Union of both passes per key — higher confidence wins, nothing dropped."""
    best: dict[str, ExtraValue] = {e.key: e for e in deterministic}
    for candidate in semantic:
        current = best.get(candidate.key)
        if current is None or candidate.confidence > current.confidence:
            best[candidate.key] = candidate
    return tuple(best.values())


class IntelligenceReport:
    """Everything one sync produced — the routes' single return shape."""

    __slots__ = ("state", "merged", "conflicts", "session", "document_id")

    def __init__(
        self,
        state: ProfileState,
        merged: tuple[MergedField, ...],
        conflicts: tuple[FieldConflict, ...],
        session: Session,
        document_id: str | None = None,
    ) -> None:
        self.state = state
        self.merged = merged
        self.conflicts = conflicts
        self.session = session
        # The document this call processed (None for profile reads/resolves).
        self.document_id = document_id


class DocumentIntelligenceService:
    """Run the schema-driven pipeline and keep the session in sync with it."""

    def __init__(
        self,
        uploads: UploadService,
        understanding: DocumentUnderstandingService,
        schemas: SchemaSource,
        classifier: DocumentClassifierService,
        mapper: FieldMapper,
        merge: MergeService,
        conflicts: ConflictService,
        sessions: SessionService,
        repository: ProfileRepository,
        canonical: CanonicalSchemaRegistry = canonical_registry,
        semantic: SemanticExtractorService | None = None,
    ) -> None:
        self._uploads = uploads
        self._understanding = understanding
        self._schemas = schemas
        self._classifier = classifier
        self._mapper = mapper
        self._merge = merge
        self._conflicts = conflicts
        self._sessions = sessions
        self._repository = repository
        self._canonical = canonical
        # Optional AI half of the hybrid extractor — None/unavailable means
        # the deterministic FieldMapper alone carries every document.
        self._semantic = semantic

    # ------------------------------------------------------------------ #
    # Use-cases
    # ------------------------------------------------------------------ #

    def process_document(self, document_id: str, session_id: str) -> IntelligenceReport:
        """
        Classify one uploaded document, extract its canonical fields through
        the shared schema-driven pipeline, and re-merge the session's profile.

        Raises the typed 404s for unknown documents/sessions, 422/502 for
        unreadable documents or OCR failures (from the understanding stage),
        and 500 if no document schemas are installed.
        """
        self._sessions.get_session(session_id)  # 404 fast, before OCR work
        document = self._uploads.get_document(document_id)
        record = self._understanding.process(document_id)  # cached analysis+OCR

        schemas = self._load_schemas()
        classification = self._classifier.classify(record.ocr.full_text, schemas)
        schema = self._schema_for(classification.schema_id, schemas)
        values, extras = (
            self._mapper.extract_document(record.ocr, schema)
            if schema is not None
            else ((), ())
        )
        # Hybrid pipeline (Phase 13): the semantic (Gemini) pass reads the same
        # OCR text label-independently, then both result sets are judged by the
        # SAME deterministic validators — best evidence per field wins. Any AI
        # failure degrades silently to the deterministic result alone.
        if schema is not None and self._semantic is not None:
            sem_values, sem_extras = self._semantic.extract(record.ocr, schema)
            values = _combine_canonical(values, sem_values)
            extras = _combine_extras(extras, sem_extras)

        state = self._repository.get(session_id) or ProfileState(session_id=session_id)
        existing = state.documents.get(document_id)
        sequence = (
            existing.sequence  # re-processing keeps its original upload order
            if existing is not None
            else max((d.sequence for d in state.documents.values()), default=0) + 1
        )
        state.documents[document_id] = DocumentProfile(
            document_id=document_id,
            filename=document.original_filename,
            sequence=sequence,
            classification=classification,
            values=values,
            extras=extras,
        )
        self._repository.save(state)
        logger.info(
            "Intelligence: %s classified as '%s' (%d canonical + %d extended values) for session %s",
            document_id,
            classification.schema_id,
            len(values),
            len(extras),
            session_id,
        )
        return self._sync(session_id, focus_document_id=document_id)

    def set_primary_form(self, session_id: str, form_id: str) -> IntelligenceReport:
        """
        Record the ONE primary form this session will generate as its final
        output. Supporting documents are only evidence used to autofill it.
        The choice must be an installed schema of kind 'kyc_form'.
        """
        self._sessions.get_session(session_id)  # typed 404
        schema = next(
            (s for s in self._load_schemas() if s.id == form_id and s.kind == "kyc_form"),
            None,
        )
        if schema is None:
            raise InvalidPrimaryFormError(form_id)
        state = self._repository.get(session_id) or ProfileState(session_id=session_id)
        state.primary_form_id = schema.id
        state.primary_form_label = schema.label
        state.updated_at = utc_now()
        self._repository.save(state)
        logger.info("Intelligence: session %s primary form -> %s", session_id, schema.id)
        return self._sync(session_id)

    def get_profile(self, session_id: str) -> IntelligenceReport:
        """Return the session's unified profile, re-synced (prune + merge + apply)."""
        self._sessions.get_session(session_id)  # typed 404
        return self._sync(session_id)

    def resolve_conflict(
        self,
        session_id: str,
        canonical_id: str,
        document_id: str | None = None,
        value: str | None = None,
    ) -> IntelligenceReport:
        """Record the user's choice for a conflicted field, then re-sync."""
        report = self._sync(session_id)  # fresh conflicts to resolve against
        self._conflicts.resolve(
            report.state, report.conflicts, canonical_id, document_id, value
        )
        self._repository.save(report.state)
        return self._sync(session_id)

    def forget_session(self, session_id: str) -> bool:
        """Drop a session's profile state (used when the session is deleted)."""
        return self._repository.delete(session_id)

    # ------------------------------------------------------------------ #
    # The sync engine: prune -> merge -> detect conflicts -> apply/retract
    # ------------------------------------------------------------------ #

    def _sync(self, session_id: str, focus_document_id: str | None = None) -> IntelligenceReport:
        state = self._repository.get(session_id) or ProfileState(session_id=session_id)

        # 1. Prune documents that were deleted since the last sync — their
        #    contributions (and any answers they produced) must vanish.
        for doc_id in list(state.documents):
            try:
                self._uploads.get_document(doc_id)
            except DocumentNotFoundError:
                del state.documents[doc_id]
                logger.info(
                    "Intelligence: pruned deleted document %s from session %s",
                    doc_id,
                    session_id,
                )

        # 2. Merge everything that remains; conflicts honor prior resolutions.
        outcome = self._merge.merge(state)
        promoted, conflicts = self._conflicts.detect(outcome.disputed, state.resolutions)
        merged = outcome.merged + promoted

        # Resolutions are re-derived from what actually survived detection, so
        # a choice whose source document is gone doesn't linger forever.
        state.resolutions = {
            c.canonical_id: c.resolved_value
            for c in conflicts
            if c.resolved and c.resolved_value is not None
        }

        # 3. Apply the merged profile to the interview session (and retract
        #    answers this pipeline wrote that are no longer supported).
        open_conflicts = {c.canonical_id for c in conflicts if not c.resolved}
        session = self._apply(session_id, state, merged, open_conflicts)

        state.updated_at = utc_now()
        self._repository.save(state)
        return IntelligenceReport(
            state=state,
            merged=merged,
            conflicts=conflicts,
            session=session,
            document_id=focus_document_id,
        )

    def _apply(
        self,
        session_id: str,
        state: ProfileState,
        merged: tuple[MergedField, ...],
        open_conflicts: set[str],
    ) -> Session:
        """
        Write merged values into the session through the NORMAL answer path
        (so the deterministic Validation Engine rules on every one of them),
        under three iron rules:

          * an answer the user gave themselves is NEVER overwritten;
          * a field with an open conflict is never auto-filled — it stays
            pending until the user chooses;
          * only answers this pipeline itself wrote are ever updated/retracted.
        """
        session = self._sessions.get_session(session_id)

        # Only merged values that ALREADY passed validation and clear the
        # prefill confidence bar are ever auto-applied — an uncertain OCR
        # guess must never silently become an official answer; the interview
        # asks instead. A value the user explicitly chose in a conflict is
        # exempt from the confidence bar: a human decision, not a guess.
        eligible = {
            m.canonical_id: m
            for m in merged
            if m.canonical_id not in open_conflicts
            and m.validated
            and (m.resolved or m.confidence >= settings.PREFILL_CONFIDENCE_THRESHOLD)
        }

        # Retract: previously-applied answers that are no longer supported
        # (source deleted, merged winner changed to something ineligible, or
        # the field fell into an open conflict) — but only if they are still
        # OURS (untouched by the user) in the session.
        for canonical_id, applied in list(state.applied.items()):
            if canonical_id in eligible:
                continue
            if session.answers.get(applied.field_id) == applied.value:
                session = self._sessions.clear_answer(session_id, applied.field_id)
            del state.applied[canonical_id]

        # Apply: eligible values into unanswered (or pipeline-owned) fields.
        # Validation runs after merging, on every write.
        for item in eligible.values():
            field = self._canonical.session_field(item.canonical_id)
            if field is None:
                continue  # profile-only canonical field
            new_value = item.value.strip()
            current = session.answers.get(field.id)
            prior = state.applied.get(item.canonical_id)
            if current is not None and (prior is None or prior.value != current):
                continue  # a human answer outranks a machine merge — always
            if current == new_value:
                # Already in place; just make sure ownership is recorded.
                state.applied[item.canonical_id] = AppliedAnswer(
                    field_id=field.id, value=new_value
                )
                continue
            session, result = self._sessions.update_answer(session_id, field.id, new_value)
            if result.valid and field.id in session.answers:
                state.applied[item.canonical_id] = AppliedAnswer(
                    field_id=field.id, value=session.answers[field.id]
                )
            else:
                state.applied.pop(item.canonical_id, None)
        return self._sessions.get_session(session_id)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _load_schemas(self) -> tuple[DocumentSchema, ...]:
        schemas = self._schemas.load_all()
        if not schemas:
            raise DocumentSchemasMissingError(directory=settings.DOCUMENT_SCHEMAS_DIR)
        return schemas

    @staticmethod
    def _schema_for(
        schema_id: str, schemas: tuple[DocumentSchema, ...]
    ) -> DocumentSchema | None:
        """The classified schema, or the generic 'unknown' fallback schema."""
        by_id = {schema.id: schema for schema in schemas}
        matched = by_id.get(schema_id)
        if matched is not None:
            return matched
        # Unknown document: fall back to the generic document-wide schema so
        # unambiguous values (a PAN, an email) are still harvested.
        return next((s for s in schemas if s.kind == "unknown"), None)
