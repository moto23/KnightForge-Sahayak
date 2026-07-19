"""
PDFGenerationService — produce the final filled KYC PDF from a session.

Phase 8's orchestrator (requirement 5). For one generation request it:

  1. loads the session                                    -> 404 session_not_found
  2. verifies the interview is COMPLETE (all required
     fields validly answered)                             -> 409 interview_incomplete
                                                             WITH the missing field ids
  3. builds the overlay plan from Session.answers — the
     SINGLE SOURCE OF TRUTH; OCR results are never read
  4. loads the original template bytes                    -> 500 pdf_template_missing/corrupt
  5. renders via the PDFGenerator port                    -> 500 pdf_generation_failed
  6. writes <uuid>.pdf under generated_pdfs/ (never
     overwrites: fresh uuid per generation)               -> 500 pdf_generation_failed
  7. registers metadata and returns the record

Download/read/delete of generated files also live here so routes stay
logic-free. All PDF-library work happens behind the PDFGenerator port.
"""

import logging
import uuid
from pathlib import Path

from app.core.config import Settings, settings
from app.core.exceptions import (
    GeneratedPdfNotFoundError,
    InterviewIncompleteError,
    NoActivePrimaryFormError,
    PdfGenerationError,
    PdfTemplateCorruptError,
    PdfTemplateNotFoundError,
)
from app.domain.next_question import NextQuestionEngine, next_question_engine
from app.domain.canonical_schema import CanonicalSchemaRegistry, canonical_registry
from app.domain.pdf import GeneratedPdf, fingerprint_answers
from app.services.form_service import FormService, form_service
from app.domain.repositories import GeneratedPdfRepository, PDFGenerator
from app.services.coordinate_mapper import CoordinateMapper
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)


class PDFGenerationService:
    """Generate, fetch, download, and delete filled KYC PDFs."""

    def __init__(
        self,
        sessions: SessionService,
        mapper: CoordinateMapper,
        generator: PDFGenerator,
        repository: GeneratedPdfRepository,
        config: Settings = settings,
        next_engine: NextQuestionEngine = next_question_engine,
        intelligence=None,
        uploads=None,
        filler=None,
        assets=None,
        layouts=None,
        forms: FormService = form_service,
        canonical: CanonicalSchemaRegistry = canonical_registry,
    ) -> None:
        self._sessions = sessions
        self._mapper = mapper
        self._generator = generator
        self._repository = repository
        self._next_engine = next_engine
        # Optional collaborators for completing the user's uploaded form.
        # All None (e.g. in isolated tests) simply keeps the template path.
        self._intelligence = intelligence
        self._uploads = uploads
        self._filler = filler
        # Supplies photograph/signature bytes for placement. None simply means
        # no images are drawn — the text fill is unaffected.
        self._assets = assets
        # Per-form placement manifests. None = semantic fallback only.
        self._layouts = layouts
        self._forms = forms
        self._canonical = canonical
        self._template_path = Path(config.PDF_TEMPLATE_PATH)
        self._output_dir = Path(config.GENERATED_PDF_DIR)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Generation
    # ------------------------------------------------------------------ #

    def generate(self, session_id: str) -> GeneratedPdf:
        """
        Produce the filled PDF for one completed interview session.

        Session.answers is the only data source. Raises the typed 409 with
        the exact missing field ids if any required field is unanswered.
        """
        session = self._sessions.get_session(session_id)  # 404 if unknown

        # No active form => nothing to generate. An EMPTY required scope means
        # a primary form was retired (its document was deleted), which must not
        # be mistaken for "every requirement is satisfied" — without this the
        # empty scope trivially passes the completion gate below and the user
        # gets a PDF of a form they no longer have.
        if session.required_field_ids is not None and not session.required_field_ids:
            raise NoActivePrimaryFormError()

        # Completion gate (requirement 10): recomputed here, not trusted from
        # the stored status flag, so a stale session can't slip through.
        remaining = self._next_engine.remaining_required_fields(
            session.answers, session.required_field_ids
        )
        if remaining:
            raise InterviewIncompleteError(tuple(f.id for f in remaining))

        # Preferred path: complete the user's OWN uploaded form so they get
        # their SBI/HDFC/ICICI/Axis document back, not a recreated CVL page.
        # Falls back to the bundled coordinate template when no form was
        # uploaded (guest quick-start, interview-only flows).
        uploaded = self._fill_uploaded_form(session_id, session.answers)
        if uploaded is not None:
            pdf_bytes, template_id, template_version, filled_count = uploaded
            return self._store(
                session_id=session_id,
                session=session,
                pdf_bytes=pdf_bytes,
                template_id=template_id,
                template_version=template_version,
                fields_filled=filled_count,
            )

        plan = self._mapper.build_plan(session.answers)
        template_bytes = self._read_template()

        try:
            pdf_bytes = self._generator.render(template_bytes, plan)
        except ValueError as exc:  # corrupt/unopenable template
            raise PdfTemplateCorruptError(str(exc)) from exc
        except Exception as exc:  # rendering failure
            raise PdfGenerationError(str(exc)) from exc

        return self._store(
            session_id=session_id,
            session=session,
            pdf_bytes=pdf_bytes,
            template_id=plan.template_id,
            template_version=plan.template_version,
            fields_filled=len(session.answers) - len(plan.unmapped_fields),
        )

    # ------------------------------------------------------------------ #
    # Uploaded-form completion
    # ------------------------------------------------------------------ #

    def _fill_uploaded_form(
        self, session_id: str, answers: dict[str, str]
    ) -> tuple[bytes, str, str, int] | None:
        """
        Complete the user's own uploaded primary form.

        Returns (pdf bytes, template id, template version, fields placed), or
        None when this session has no usable uploaded form — in which case the
        caller falls back to the bundled template. Never raises for content
        problems: an unfillable upload simply returns None so the user still
        gets a PDF.
        """
        if self._intelligence is None or self._uploads is None or self._filler is None:
            return None
        try:
            # Re-sync first: a primary form deleted since the last request must
            # be retired BEFORE we try to fill it, otherwise a stale id would
            # keep a deleted document as the generation target.
            self._intelligence.get_profile(session_id)
            state = self._intelligence.profile_state(session_id)
            if state is None or not state.primary_document_id:
                return None
            document_id = state.primary_document_id
            source = self._uploads.read_content(
                self._uploads.get_document(document_id)
            )
            if not source[:5].startswith(b"%PDF"):
                # A photographed form can be classified and extracted from, but
                # cannot be filled as a PDF — fall back to the template.
                logger.info(
                    "Primary document %s is not a PDF; using bundled template",
                    document_id,
                )
                return None
            schema = self._intelligence.schema_for_session(session_id)
            labels, options = self._fill_vocabulary(schema)
            # The form's placement manifest, when one exists. It states exactly
            # where each field lives on THIS form; without it the engine falls
            # back to unambiguous caption discovery only.
            layout = (
                self._layouts.load(schema.id)
                if self._layouts is not None and schema is not None
                else None
            )
            filled_bytes, filled, unplaced = self._filler.fill(
                source,
                answers,
                labels,
                options,
                layout,
                assets=self._session_assets(session_id),
                asset_requirements=self._intelligence.asset_requirements(session_id),
            )
            if not filled:
                logger.warning(
                    "Nothing could be placed on uploaded form %s; using template",
                    document_id,
                )
                return None
            if unplaced:
                logger.info("Uploaded form: %d field(s) unplaced: %s", len(unplaced), unplaced)
            template_id = schema.id if schema else "uploaded_form"
            return filled_bytes, template_id, "uploaded", len(filled)
        except Exception:  # noqa: BLE001 - never block PDF generation
            logger.exception("Uploaded-form fill failed; falling back to template")
            return None

    def _session_assets(self, session_id: str) -> dict:
        """
        The photograph/signature bytes to draw, keyed by kind.

        Missing or unreadable assets are simply omitted: a PDF must still be
        produced (the interview gate already guarantees a REQUIRED asset was
        supplied), and the filler reports anything it could not place.
        """
        if self._assets is None:
            return {}
        from app.domain.form_assets import AssetKind

        found = {}
        for kind in AssetKind:
            content = self._assets.bytes_for(session_id, kind)
            if content:
                found[kind] = content
        return found

    def _fill_vocabulary(
        self, schema
    ) -> tuple[dict[str, tuple[str, ...]], dict[str, dict[str, tuple[str, ...]]]]:
        """
        Build the label/option captions the filler searches the page for.

        Captions come from the interview schema (display names + option
        labels) and, when available, the document schema's own aliases — so a
        form that prints "Customer Name" is matched as readily as one printing
        "Name of Applicant".
        """
        labels: dict[str, tuple[str, ...]] = {}
        options: dict[str, dict[str, tuple[str, ...]]] = {}
        alias_by_session_field: dict[str, list[str]] = {}
        if schema is not None:
            for rule in schema.fields:
                if rule.is_extra or not rule.canonical:
                    continue
                field = self._canonical.session_field(rule.canonical)
                if field is None:
                    continue
                alias_by_session_field.setdefault(field.id, []).extend(rule.labels)

        for field in self._forms.get_all_fields():
            captions = [field.display_name, *alias_by_session_field.get(field.id, [])]
            labels[field.id] = tuple(dict.fromkeys(c for c in captions if c))
            if field.options:
                options[field.id] = {
                    option.value.lower(): (option.label, option.value)
                    for option in field.options
                }
        return labels, options

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _store(
        self,
        session_id: str,
        session,
        pdf_bytes: bytes,
        template_id: str,
        template_version: str,
        fields_filled: int,
    ) -> GeneratedPdf:
        """Write the produced bytes + immutable history record (one path)."""
        pdf_id = str(uuid.uuid4())
        stored_filename = f"{pdf_id}.pdf"
        target = self._output_dir / stored_filename
        try:
            # 'xb' = exclusive create: even a uuid collision cannot overwrite.
            with open(target, "xb") as fh:
                fh.write(pdf_bytes)
        except OSError as exc:
            raise PdfGenerationError(f"could not write output file: {exc}") from exc

        record = GeneratedPdf(
            pdf_id=pdf_id,
            stored_filename=stored_filename,
            generated_by_session=session_id,
            template_id=template_id,
            template_version=template_version,
            page_count=self._generator.page_count(pdf_bytes),
            file_size=len(pdf_bytes),
            fields_filled=fields_filled,
            # Snapshot of exactly what was rendered, so this record can later
            # be told apart from a session that has since moved on.
            answers_fingerprint=fingerprint_answers(session.answers),
        )
        try:
            self._repository.add(record)
        except Exception:
            target.unlink(missing_ok=True)  # roll back the file on metadata failure
            raise

        logger.info(
            "PDF generated: id=%s session=%s template=%s fields=%d size=%d",
            pdf_id, session_id, template_id, record.fields_filled, record.file_size,
        )
        return record

    # ------------------------------------------------------------------ #
    # Queries / download / delete
    # ------------------------------------------------------------------ #

    def get_record(self, pdf_id: str) -> GeneratedPdf:
        """Metadata for one generated PDF, or the typed 404."""
        record = self._repository.get(pdf_id)
        if record is None:
            raise GeneratedPdfNotFoundError(pdf_id)
        return record

    def list_records(self) -> tuple[GeneratedPdf, ...]:
        """Every generated PDF's metadata, newest first."""
        return self._repository.list_all()

    def file_path(self, pdf_id: str) -> Path:
        """
        Absolute path of a generated PDF for download streaming.

        Raises the typed 404 if the record OR the file is missing (a record
        whose file vanished from disk must not 500).
        """
        record = self.get_record(pdf_id)
        path = self._output_dir / record.stored_filename
        if not path.exists():
            logger.error("Generated PDF file missing on disk: %s", path)
            raise GeneratedPdfNotFoundError(pdf_id)
        return path.resolve()

    def delete(self, pdf_id: str) -> GeneratedPdf:
        """Remove a generated PDF's file and metadata; return the record."""
        record = self.get_record(pdf_id)
        (self._output_dir / record.stored_filename).unlink(missing_ok=True)
        self._repository.delete(pdf_id)
        logger.info("Generated PDF deleted: %s", pdf_id)
        return record

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _read_template(self) -> bytes:
        """Load the blank template PDF; typed 500s for missing/unreadable."""
        if not self._template_path.exists():
            raise PdfTemplateNotFoundError(
                f"template not found at {self._template_path}"
            )
        try:
            return self._template_path.read_bytes()
        except OSError as exc:
            raise PdfTemplateCorruptError(f"template unreadable: {exc}") from exc
