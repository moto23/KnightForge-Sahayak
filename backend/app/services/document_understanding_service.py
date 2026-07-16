"""
DocumentUnderstandingService — the Phase 7 pipeline orchestrator.

Composes the whole flow the phase's architecture diagram describes:

    Upload -> DocumentAnalysisService -> OCRService(OCRProvider)
           -> ExtractionEngine(ConfidenceEngine + ValidationEngine)
           -> SessionPrefillService

Each stage stays single-responsibility; THIS service owns only sequencing,
caching, and fetching document bytes through the Phase 6 ports. Results are
cached per document (OCR is expensive), so reading, re-extracting, and
prefilling after the first run are free.
"""

import logging

from app.core.exceptions import DocumentNotProcessedError
from app.domain.extraction import DocumentUnderstanding, PrefillReport
from app.domain.repositories import DocumentUnderstandingRepository
from app.services.document_analysis_service import DocumentAnalysisService
from app.services.extraction_engine import ExtractionEngine
from app.services.ocr_service import OCRService
from app.services.session_prefill_service import SessionPrefillService
from app.services.upload_service import UploadService

logger = logging.getLogger(__name__)


class DocumentUnderstandingService:
    """Run (and cache) the full understanding pipeline for uploaded documents."""

    def __init__(
        self,
        uploads: UploadService,
        analysis: DocumentAnalysisService,
        ocr: OCRService,
        extraction: ExtractionEngine,
        prefill: SessionPrefillService,
        repository: DocumentUnderstandingRepository,
    ) -> None:
        self._uploads = uploads
        self._analysis = analysis
        self._ocr = ocr
        self._extraction = extraction
        self._prefill = prefill
        self._repository = repository

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #

    def process(self, document_id: str, force: bool = False) -> DocumentUnderstanding:
        """
        Run analysis -> OCR -> extraction for one uploaded document.

        Idempotent: a cached result is returned unless `force` re-runs the
        pipeline (e.g. after a Tesseract upgrade). Raises the typed 404 for
        unknown documents, 422 for unreadable ones, 502 for engine outages.
        """
        if not force:
            cached = self._repository.get(document_id)
            if cached is not None:
                logger.info("Understanding cache hit for %s", document_id)
                return cached

        document = self._uploads.get_document(document_id)  # 404 if unknown
        content = self._uploads.read_content(document)

        analysis = self._analysis.analyze(document, content)
        ocr = self._ocr.read_document(analysis, content)
        extraction = self._extraction.extract(ocr)

        record = DocumentUnderstanding(
            document_id=document_id,
            analysis=analysis,
            ocr=ocr,
            extraction=extraction,
        )
        self._repository.save(record)
        logger.info(
            "Pipeline complete for %s: %d fields extracted, %d accepted",
            document_id,
            len(extraction.fields),
            len(extraction.accepted_fields),
        )
        return record

    def get_processed(self, document_id: str) -> DocumentUnderstanding:
        """
        Return the cached pipeline result WITHOUT running anything.

        Raises DocumentNotFoundError (404) if the document doesn't exist, or
        DocumentNotProcessedError (404) if it was uploaded but never processed.
        """
        self._uploads.get_document(document_id)  # distinguish the two 404s
        record = self._repository.get(document_id)
        if record is None:
            raise DocumentNotProcessedError(document_id)
        return record

    def prefill_session(
        self, document_id: str, session_id: str, overwrite: bool = False
    ) -> PrefillReport:
        """
        Prefill an interview session from a document, processing it first if
        needed. Only accepted (valid + high-confidence) fields are written.
        """
        record = self.process(document_id)  # cache-aware
        return self._prefill.prefill(session_id, record.extraction, overwrite=overwrite)

    def forget(self, document_id: str) -> bool:
        """Drop the cached result (used when the document itself is deleted)."""
        return self._repository.delete(document_id)
