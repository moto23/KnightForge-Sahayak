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
    PdfGenerationError,
    PdfTemplateCorruptError,
    PdfTemplateNotFoundError,
)
from app.domain.next_question import NextQuestionEngine, next_question_engine
from app.domain.pdf import GeneratedPdf
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
    ) -> None:
        self._sessions = sessions
        self._mapper = mapper
        self._generator = generator
        self._repository = repository
        self._next_engine = next_engine
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

        # Completion gate (requirement 10): recomputed here, not trusted from
        # the stored status flag, so a stale session can't slip through.
        remaining = self._next_engine.remaining_required_fields(session.answers)
        if remaining:
            raise InterviewIncompleteError(tuple(f.id for f in remaining))

        plan = self._mapper.build_plan(session.answers)
        template_bytes = self._read_template()

        try:
            pdf_bytes = self._generator.render(template_bytes, plan)
        except ValueError as exc:  # corrupt/unopenable template
            raise PdfTemplateCorruptError(str(exc)) from exc
        except Exception as exc:  # rendering failure
            raise PdfGenerationError(str(exc)) from exc

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
            template_id=plan.template_id,
            template_version=plan.template_version,
            page_count=self._generator.page_count(pdf_bytes),
            file_size=len(pdf_bytes),
            fields_filled=len(session.answers) - len(plan.unmapped_fields),
        )
        try:
            self._repository.add(record)
        except Exception:
            target.unlink(missing_ok=True)  # roll back the file on metadata failure
            raise

        logger.info(
            "PDF generated: id=%s session=%s fields=%d size=%d engine=%s",
            pdf_id, session_id, record.fields_filled, record.file_size,
            self._generator.engine_name(),
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
