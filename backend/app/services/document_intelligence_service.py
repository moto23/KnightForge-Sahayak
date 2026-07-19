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
import re
import threading
from collections import defaultdict

from app.core.config import settings
from app.core.exceptions import (
    DocumentNotFoundError,
    DocumentSchemasMissingError,
    InvalidPrimaryFormError,
    NotAPrimaryFormError,
    PrimaryFormInSupportingSlotError,
)
from app.domain.form_assets import (
    ASSET_FIELD_IDS,
    AssetKind,
    FormAssetRequirements,
)
from app.services.form_asset_detector import FormAssetDetector, form_asset_detector
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
from app.domain.session import ConditionalRequirement, Session, utc_now
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


_SECTION_HEADING = re.compile(r"^\s*[A-Za-z0-9]{1,2}\s*[.)]\s+\S")
_BLANK_LINE_LABEL = re.compile(r"^line\s*\d+$", re.I)


def _is_form_furniture(value: str, label_vocabulary: set[str]) -> bool:
    """
    Is this "value" actually part of the blank form rather than an answer?

    Label-anchored extraction reads whatever follows a caption. On a form that
    has NOT been filled in, what follows a caption is the NEXT caption — so a
    blank CVL page yields address="Line 2" and state="B. Proof of Identity".
    Those score high confidence and pass validation, so nothing downstream
    catches them; they reach the canonical profile and then get printed onto
    the applicant's form as if they were real data.

    Judged against the form's OWN label vocabulary, so this stays schema-driven
    rather than a blocklist tuned to one PDF.
    """
    text = value.strip()
    if not text:
        return True
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()
    if not normalized:
        return True
    if normalized in label_vocabulary:
        return True
    # "B. Proof of Identity", "2. Address Details" - a numbered section title.
    if _SECTION_HEADING.match(text):
        return True
    # "Line 2", "Line3" - the blank address rows of every one of these forms.
    if _BLANK_LINE_LABEL.match(normalized):
        return True
    return False


def _strip_form_furniture(
    values: tuple[CanonicalValue, ...], schema: DocumentSchema | None
) -> tuple[CanonicalValue, ...]:
    """Drop canonical values that are really the form's own printed labels."""
    if schema is None:
        return values
    vocabulary = {
        re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", label.lower())).strip()
        for rule in schema.fields
        for label in rule.labels
    }
    vocabulary.discard("")
    kept = tuple(v for v in values if not _is_form_furniture(v.value, vocabulary))
    dropped = len(values) - len(kept)
    if dropped:
        logger.info(
            "Discarded %d extracted value(s) that were the form's own labels", dropped
        )
    return kept


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
        assets: FormAssetDetector = form_asset_detector,
        layouts=None,
        primary_extractor=None,
        asset_repository=None,
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
        # Reads the uploaded form's own photo/signature boxes. Pure geometry —
        # no image ever leaves the process for this.
        self._assets = assets
        # Measured per-form geometry + the region reader that uses it. Both
        # None simply keeps the previous label-anchored extraction.
        self._layouts = layouts
        self._primary_extractor = primary_extractor
        # Read-only view of stored photo/signature files, so activating a form
        # can re-adopt an asset the session already holds. None simply skips
        # adoption (isolated tests), leaving the previous behaviour.
        self._asset_repository = asset_repository
        # Uploading several documents at once lands concurrent requests on one
        # session. Every mutation here is read-modify-write on a single
        # ProfileState, so without serializing per session two documents can
        # interleave and one silently loses its contribution.
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    def _session_lock(self, session_id: str) -> threading.Lock:
        """One lock per session (created on demand, never contended globally)."""
        with self._locks_guard:
            return self._locks[session_id]

    # ------------------------------------------------------------------ #
    # Use-cases
    # ------------------------------------------------------------------ #

    def process_document(
        self, document_id: str, session_id: str, is_primary: bool = False
    ) -> IntelligenceReport:
        """
        Classify one uploaded document, extract its canonical fields through
        the shared schema-driven pipeline, and re-merge the session's profile.

        Raises the typed 404s for unknown documents/sessions, 422/502 for
        unreadable documents or OCR failures (from the understanding stage),
        and 500 if no document schemas are installed.
        """
        self._sessions.get_session(session_id)  # 404 fast, before OCR work
        document = self._uploads.get_document(document_id)
        # OCR + AI extraction happen OUTSIDE the session lock: they are the
        # slow part and touch no shared state, so parallel uploads still
        # process in parallel. Only the merge/apply below is serialized.
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

        # A KYC FORM is the one document type whose blank captions sit exactly
        # where its values go, so label-anchored extraction mistakes the layout
        # for content. Identity documents (a PAN card, an Aadhaar) do not have
        # that problem and are left alone.
        if schema is not None and schema.kind == "kyc_form":
            # A KYC form is mostly captions, so "text near a label" is usually
            # ANOTHER label. Where the form has measured field geometry, read
            # each value out of its own box instead and use ONLY that: the
            # page-wide search cannot be made safe on a document whose layout
            # is indistinguishable from its content.
            region_values = self._extract_from_regions(document_id, schema)
            if region_values is not None:
                values = region_values
            else:
                values = _strip_form_furniture(values, schema)

        # Slot validation, on CONTENT rather than filename, and BEFORE any
        # state is written: a PAN card must never activate a primary form, and
        # a real KYC form dropped into the supporting box must be redirected
        # rather than silently merged as evidence for itself.
        self._enforce_slot(classification, is_primary)

        with self._session_lock(session_id):
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
            # Remember which upload IS the form to complete. Explicit intent
            # from the UI wins; otherwise the first KYC form uploaded stands in,
            # so the feature also works for a plain "upload my form" flow.
            if is_primary or (
                state.primary_document_id is None
                and classification.kind == "kyc_form"
            ):
                state.primary_document_id = document_id
                # A newly uploaded primary ACTIVATES its own schema, replacing
                # whatever was active before, so Progress and the interview
                # rebuild against the form actually in front of the user. The
                # merge below then remaps existing evidence onto it.
                detected = (
                    schema
                    if schema is not None and schema.kind == "kyc_form"
                    else None
                )
                if detected is not None:
                    # Inspect THIS file for photo/signature boxes: the same
                    # bank's form differs between a scanned copy and an
                    # AcroForm one, so the uploaded document — not the schema
                    # alone — decides what the applicant is asked for.
                    self._activate_primary_form(
                        state,
                        session_id,
                        detected,
                        assets=self._detect_assets(document_id, detected),
                    )
            self._repository.save(state)
            report = self._sync(session_id, focus_document_id=document_id)
        logger.info(
            "Intelligence: %s classified as '%s' (%d canonical + %d extended values) for session %s",
            document_id,
            classification.schema_id,
            len(values),
            len(extras),
            session_id,
        )
        return report

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
        # Nothing uploaded to inspect here — the form was only SELECTED — so
        # asset requirements come from its JSON declaration. If the user later
        # uploads the form itself, process_document re-detects from the real
        # file and overrides this.
        self._activate_primary_form(
            state,
            session_id,
            schema,
            assets=self._assets.detect(
                None,
                schema_photo=schema.requires_photo,
                schema_signature=schema.requires_signature,
            ),
        )
        state.updated_at = utc_now()
        self._repository.save(state)
        return self._sync(session_id)

    def _extract_from_regions(
        self, document_id: str, schema: DocumentSchema
    ) -> tuple[CanonicalValue, ...] | None:
        """
        Read a primary form's values from its manifest field regions.

        Returns None when this form has no manifest, so the caller keeps the
        previous label-anchored behaviour rather than losing extraction
        entirely. An empty tuple is a real answer: the form is blank.
        """
        if self._layouts is None or self._primary_extractor is None:
            return None
        try:
            layout = self._layouts.load(schema.id)
            if not self._primary_extractor.supports(layout):
                return None
            content = self._uploads.read_content(
                self._uploads.get_document(document_id)
            )
            if not content[:5].startswith(b"%PDF"):
                return None  # a photographed form has no measurable geometry
            return self._primary_extractor.extract(content, layout, document_id)
        except Exception:  # noqa: BLE001 - never fail an upload over extraction
            logger.exception("Region extraction failed for %s", schema.id)
            return None

    def _detect_assets(
        self, document_id: str, schema: DocumentSchema
    ) -> FormAssetRequirements:
        """
        Inspect an uploaded primary form for its photo/signature boxes.

        Falls back to the schema's declaration when the bytes cannot be read —
        a form that declares a photo box still asks for one, so a failed
        inspection degrades to "ask" rather than to "silently skip".
        """
        try:
            document = self._uploads.get_document(document_id)
            content = self._uploads.read_content(document)
        except Exception:  # noqa: BLE001
            content = None
        return self._assets.detect(
            content,
            schema_photo=schema.requires_photo,
            schema_signature=schema.requires_signature,
        )

    def asset_requirements(self, session_id: str) -> FormAssetRequirements | None:
        """
        What the ACTIVE primary form requires, or None when no form is active.

        None is meaningful: with no active form there is no page to place an
        image on, so no asset may be collected.
        """
        state = self._repository.get(session_id)
        return state.asset_requirements if state is not None else None

    def _activate_primary_form(
        self,
        state: ProfileState,
        session_id: str,
        schema: DocumentSchema,
        assets: FormAssetRequirements | None = None,
    ) -> None:
        """
        Make `schema` the session's active form: record it and scope the
        interview / progress / PDF gate to ITS requirements.

        The single place a form becomes active — used both when the user picks
        one and when an uploaded document is detected as one, so the two paths
        can never drift.
        """
        state.primary_form_id = schema.id
        state.primary_form_label = schema.label
        state.asset_requirements = assets
        # Switching forms can drop a requirement (the old form had a photo box,
        # the new one doesn't). Retract the now-pointless answer so nothing
        # counts toward a completion the new form never asked for.
        self._retract_unwanted_assets(session_id, assets)
        # ...and the mirror image: a form can ADD a requirement the session can
        # already satisfy, because the image file outlives the answer. Without
        # this the interview asks for a photograph that is sitting in the
        # session, and "Keep & Continue" hands back the same question forever.
        self._adopt_available_assets(session_id, assets)
        self._sessions.set_required_fields(
            session_id,
            self._required_session_fields(schema, assets),
            [
                ConditionalRequirement(
                    field_id=rule.field_id,
                    when_field=rule.when_field,
                    equals=rule.equals,
                    unless_answered=rule.unless_answered,
                )
                for rule in schema.conditional_required
            ],
        )
        logger.info("Intelligence: session %s primary form -> %s", session_id, schema.id)

    def _deactivate_primary_form(self, state: ProfileState, session_id: str) -> None:
        """
        Retire the active form after its uploaded document was deleted.

        Answers are NOT touched here — the merge that follows re-derives every
        canonical value from the remaining evidence, and answers the user gave
        themselves are preserved by the normal apply/retract rules.
        """
        state.primary_document_id = None
        state.primary_form_id = None
        state.primary_form_label = None
        # No active form means no photo box and no signature line exist any
        # more. Clear both the requirement and any answer they produced, or
        # Progress keeps showing "Photo pending" for a form that is gone.
        state.asset_requirements = None
        self._retract_unwanted_assets(session_id, None)
        # EMPTY scope, not None. The primary form defines the workflow, so with
        # it gone there is no questionnaire at all: no required fields, no
        # progress percentage, no interview questions, and no PDF generation
        # until a new primary form is uploaded. Passing None here would revert
        # to the registry's default required set and leave the user staring at
        # a live interview for a form they just deleted.
        self._sessions.set_required_fields(session_id, [], [])
        logger.info(
            "Intelligence: primary form retired for session %s (document deleted)",
            session_id,
        )

    def _retract_unwanted_assets(
        self, session_id: str, assets: FormAssetRequirements | None
    ) -> None:
        """
        Clear asset answers the (new) active form does not ask for.

        `clear_answer` rather than a blank submission: the field must return to
        PENDING, not to "invalid". Stored image files are cleaned up separately
        by AssetService — this only touches interview state, keeping the two
        responsibilities apart.
        """
        for kind, field_id in ASSET_FIELD_IDS.items():
            if assets is not None and assets.requires(kind):
                continue
            try:
                self._sessions.clear_answer(session_id, field_id)
            except Exception:  # noqa: BLE001 - unknown field/session must not break activation
                logger.debug("Could not clear asset field %s on %s", field_id, session_id)

    def _adopt_available_assets(
        self, session_id: str, assets: FormAssetRequirements | None
    ) -> None:
        """
        Re-answer an asset field the session can already satisfy.

        The stored image and the interview answer are two different things, and
        only the upload path ever wrote the answer. So every route that cleared
        it - switching to a form with no photo box, deleting the primary form -
        left the FILE behind and the answer gone, permanently. Activating a form
        that wants a photograph again then asked for one the session was still
        holding: Progress counted it pending, and because the requirement reads
        `provided` from the file it showed as supplied, so the interview offered
        "Keep & Continue" and then returned the very same question.

        Idempotent by construction: a field that already has an answer is left
        exactly as it is, so this is safe to run on every activation.
        """
        if self._asset_repository is None or assets is None:
            return
        try:
            session = self._sessions.get_session(session_id)
        except Exception:  # noqa: BLE001 - never break activation over this
            logger.debug("Could not read session %s to adopt assets", session_id)
            return
        for kind, field_id in ASSET_FIELD_IDS.items():
            if not assets.requires(kind) or field_id in session.answers:
                continue
            stored = self._asset_repository.get(session_id, kind)
            if stored is None:
                continue
            try:
                self._sessions.update_answer(session_id, field_id, stored.asset_id)
                logger.info(
                    "Intelligence: re-adopted stored %s for session %s",
                    kind.value, session_id,
                )
            except Exception:  # noqa: BLE001
                logger.debug("Could not adopt asset %s on %s", field_id, session_id)

    @staticmethod
    def _enforce_slot(classification, is_primary: bool) -> None:
        """
        Refuse a document uploaded into the wrong slot.

        Judged purely on what the CLASSIFIER found in the content, so renaming
        'pan.jpg' to 'sbi-kyc-form.pdf' changes nothing. Unknown/unclassified
        supporting documents are deliberately still accepted — readable
        evidence is useful even when the type is not recognised.
        """
        is_kyc_form = classification.kind == "kyc_form"
        if is_primary and not is_kyc_form:
            raise NotAPrimaryFormError(classification.label)
        if not is_primary and is_kyc_form:
            raise PrimaryFormInSupportingSlotError(classification.label)

    def _required_session_fields(
        self, schema: DocumentSchema, assets: FormAssetRequirements | None = None
    ) -> list[str] | None:
        """
        The interview field ids a primary form requires, or None when the form
        declares no requirements (keep the registry default).

        Photograph/signature join this set ONLY when the active form actually
        needs them — which is exactly what makes them conditional: they are
        required fields of THIS form, counted and asked like any other, and
        entirely absent for a form that has no photo box.
        """
        asset_fields = list(assets.required_field_ids) if assets is not None else []
        if (
            not schema.required_canonical
            and not schema.required_session_fields
            and not asset_fields
        ):
            return None
        field_ids: list[str] = []
        for canonical_id in schema.required_canonical:
            field = self._canonical.session_field(canonical_id)
            if field is not None and field.id not in field_ids:
                field_ids.append(field.id)
        # Form-specific mandatory fields with no canonical mapping.
        for field_id in schema.required_session_fields:
            if field_id not in field_ids:
                field_ids.append(field_id)
        # Photo/signature last: they are signed at the END of a printed form.
        for field_id in asset_fields:
            if field_id not in field_ids:
                field_ids.append(field_id)
        return field_ids or None

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
        with self._session_lock(session_id):
            report = self._sync(session_id)  # fresh conflicts to resolve against
            self._conflicts.resolve(
                report.state, report.conflicts, canonical_id, document_id, value
            )
            self._repository.save(report.state)
            return self._sync(session_id)

    def profile_state(self, session_id: str) -> ProfileState | None:
        """Raw stored state (no sync) — used by the PDF layer to find the
        uploaded primary form. None when this session has no profile yet."""
        return self._repository.get(session_id)

    def schema_for_session(self, session_id: str) -> DocumentSchema | None:
        """
        The document schema of this session's primary form, if one is known —
        gives the PDF filler that form's own label aliases.
        """
        state = self._repository.get(session_id)
        if state is None:
            return None
        schema_id = state.primary_form_id
        if not schema_id and state.primary_document_id:
            document = state.documents.get(state.primary_document_id)
            schema_id = document.classification.schema_id if document else None
        if not schema_id:
            return None
        return next((s for s in self._load_schemas() if s.id == schema_id), None)

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
                # Deleting the PRIMARY form must also retire the form it
                # activated: otherwise its schema keeps driving Progress, the
                # interview keeps asking its fields, and PDF generation still
                # targets a file that no longer exists.
                if doc_id == state.primary_document_id:
                    self._deactivate_primary_form(state, session_id)

        # A primary form that was only ever *selected* (never uploaded) stays
        # active — the user picked it deliberately. Only an uploaded primary
        # that has since been deleted retires the schema above.

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

    def _never_prefill(self, state: ProfileState) -> frozenset[str]:
        """Canonical ids the active form insists the user supplies themselves."""
        if not state.primary_form_id:
            return frozenset()
        for schema in self._schemas.load_all():
            if schema.id == state.primary_form_id:
                return frozenset(schema.never_prefill)
        return frozenset()

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

        # Deterministic VALIDATION is the gatekeeper here, not raw OCR
        # confidence. A merged value that passed the Validation Engine (a real
        # PAN, a checksummed Aadhaar, a sane date) is usable evidence even when
        # the scan itself read at 0.65 — which is what real photos score. The
        # old 0.75 bar silently dropped those, so the unified profile showed a
        # value while Progress and the interview still called the field
        # Pending. Anything that FAILED validation is capped at 0.35 by the
        # ConfidenceEngine and cannot pass the floor below.
        #
        # A value the user explicitly chose in a conflict always applies: a
        # human decision outranks every automatic score.
        # Fields the ACTIVE form insists on hearing from the user. Excluded here
        # rather than at extraction: the value stays visible in the profile as
        # evidence, it just never becomes an answer on its own. Being outside
        # `eligible` also retracts one applied before the form was activated.
        never_prefill = self._never_prefill(state)

        eligible = {
            m.canonical_id: m
            for m in merged
            if m.canonical_id not in open_conflicts
            and m.canonical_id not in never_prefill
            and m.validated
            and (m.resolved or m.confidence >= settings.CANONICAL_APPLY_MIN_CONFIDENCE)
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
