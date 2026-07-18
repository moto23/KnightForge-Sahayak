"""
FileSystemCorpusLoader — the CorpusLoader adapter (Phase 10).

Reads the official-document corpus from a directory:

  * .md / .txt  — read whole, treated as a single page 1
  * .pdf        — read page-by-page via PyMuPDF (same library Phase 7 already
                  confines to infrastructure; imported independently here so
                  the knowledge module never touches the OCR pipeline)

Document display names come from the first Markdown H1 when present
("# CVL KYC Form Guide"), otherwise from a prettified filename. Unreadable
files are skipped with a warning — one bad file must not sink the corpus.
"""

import logging
from pathlib import Path

from app.domain.knowledge import CorpusLoader, SourceDocument, SourcePage

try:  # Optional — without PyMuPDF the loader still handles .md/.txt.
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_TEXT_SUFFIXES = {".md", ".txt"}
_PDF_SUFFIXES = {".pdf"}


def _display_name(path: Path, text: str) -> str:
    """First Markdown H1 if present, else 'cvl-kyc-form-guide' -> 'Cvl Kyc Form Guide'."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:  # first non-empty line is not an H1 — stop looking
            break
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


class FileSystemCorpusLoader(CorpusLoader):
    """Loads .md/.txt/.pdf reference documents from a local directory."""

    def load(self, directory: str) -> tuple[SourceDocument, ...]:
        root = Path(directory)
        if not root.is_dir():
            return ()

        documents: list[SourceDocument] = []
        for path in sorted(root.iterdir()):
            suffix = path.suffix.lower()
            try:
                if suffix in _TEXT_SUFFIXES:
                    document = self._load_text(path)
                elif suffix in _PDF_SUFFIXES:
                    document = self._load_pdf(path)
                else:
                    continue  # not an ingestible type
            except Exception as exc:
                logger.warning("Skipping unreadable corpus file %s: %s", path, exc)
                continue
            if document is not None:
                documents.append(document)
        return tuple(documents)

    def _load_text(self, path: Path) -> SourceDocument | None:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return None
        return SourceDocument(
            name=_display_name(path, text),
            source=path.as_posix(),
            pages=(SourcePage(page_number=1, text=text),),
        )

    def _load_pdf(self, path: Path) -> SourceDocument | None:
        if fitz is None:
            logger.warning("PyMuPDF not installed — skipping PDF %s", path)
            return None
        pages: list[SourcePage] = []
        with fitz.open(path) as pdf:
            for number, page in enumerate(pdf, start=1):
                text = page.get_text("text")
                if text.strip():
                    pages.append(SourcePage(page_number=number, text=text))
        if not pages:
            return None  # scanned/blank PDF — nothing to index without OCR
        return SourceDocument(
            name=_display_name(path, pages[0].text),
            source=path.as_posix(),
            pages=tuple(pages),
        )
