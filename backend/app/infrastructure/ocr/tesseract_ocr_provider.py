"""
TesseractOCRProvider — the OCRProvider port implemented with Tesseract.

This adapter is the ONLY module in the codebase that imports pytesseract.
Everything upstream (OCRService, extraction, routes) depends on the abstract
OCRProvider port, so replacing Tesseract with a cloud OCR API is a one-line
binding change in the composition root.

Graceful-degradation contract (mirrors the port's docstring):
  * rotated image  -> Tesseract OSD detects orientation; the image is rotated
                      upright before recognition (reported in the result).
  * blank page     -> returns empty text with 0.0 confidence — NOT an error.
  * poor scan      -> returns whatever was read, with an honest low confidence.
  * engine broken  -> raises OCRFailedError (502) — the only failure mode.
"""

import io
import logging
import re
import shutil
from pathlib import Path

import pytesseract
from PIL import Image, ImageFilter, ImageOps

from app.core.config import Settings, settings
from app.core.exceptions import OCRFailedError
from app.domain.extraction import RecognizedText
from app.domain.repositories import OCRProvider

logger = logging.getLogger(__name__)

# Standard Windows install locations, tried when tesseract is not on PATH and
# no explicit TESSERACT_CMD is configured.
_WINDOWS_DEFAULT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

# Below this mean confidence the page is treated as unreliable enough that the
# provider retries with a different page-segmentation mode before giving up.
_RETRY_CONFIDENCE = 0.40

# The rescue ladder stops as soon as a pass reaches this confidence — extra
# passes past "clearly readable" only burn seconds.
_GOOD_ENOUGH = 0.75

# Small-angle deskew candidates tried (degrees, both directions) when a page
# stays dire after denoising — phone photos are rarely perfectly square.
_DESKEW_ANGLES = (2, -2)

# OSD must be at least this confident before we trust a rotation verdict —
# low-confidence 180° flips on dense forms are usually wrong.
_OSD_MIN_CONFIDENCE = 2.0

# Images whose short edge is below this are upscaled before recognition:
# Tesseract needs roughly >=20 px glyph height, which small phone photos and
# low-DPI scans miss. Bicubic 2x is cheap and reliably helps.
_MIN_EDGE_FOR_OCR = 1500


def _locate_tesseract(configured: str) -> str:
    """
    Resolve the tesseract executable: explicit config > PATH > known installs.

    Raises OCRFailedError if no binary can be found — surfaced as a clean 502
    instead of a cryptic pytesseract stack trace at request time.
    """
    if configured:
        if Path(configured).exists():
            return configured
        raise OCRFailedError(f"configured TESSERACT_CMD not found: {configured!r}")
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for candidate in _WINDOWS_DEFAULT_PATHS:
        if Path(candidate).exists():
            return candidate
    raise OCRFailedError(
        "tesseract executable not found. Install Tesseract OCR or set TESSERACT_CMD."
    )


class TesseractOCRProvider(OCRProvider):
    """OCRProvider adapter over the local Tesseract engine."""

    def __init__(self, config: Settings = settings) -> None:
        self._languages = config.OCR_LANGUAGES
        pytesseract.pytesseract.tesseract_cmd = _locate_tesseract(config.TESSERACT_CMD)
        # Resolve the engine version once at startup; also proves the binary runs.
        try:
            version = str(pytesseract.get_tesseract_version())
        except Exception as exc:  # pragma: no cover - startup guard
            raise OCRFailedError(f"tesseract did not start: {exc}") from exc
        self._engine_name = f"tesseract {version}"
        logger.info("TesseractOCRProvider ready: %s", self._engine_name)

    def engine_name(self) -> str:
        """Engine identifier recorded on every OCRResult."""
        return self._engine_name

    def recognize(self, image_bytes: bytes) -> RecognizedText:
        """
        Recognize the text in one PNG/JPEG image.

        Pipeline: decode -> auto-orient (OSD) -> grayscale -> recognize with
        word confidences -> retry with sparse-text mode if confidence is dire.
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image.load()
        except Exception as exc:
            # Undecodable bytes are a document problem, not an engine crash:
            # report "read nothing" so the pipeline can warn instead of die.
            logger.warning("OCR input image undecodable: %s", exc)
            return RecognizedText(text="", confidence=0.0, word_count=0)

        image, rotation = self._auto_orient(image)
        gray = image.convert("L")  # grayscale: cheap, reliable accuracy boost
        # Mild contrast normalization: washed-out photocopies and phone photos
        # gain real accuracy; already-clean scans are barely touched.
        gray = ImageOps.autocontrast(gray, cutoff=1)

        # Upscale small images: Tesseract accuracy collapses below ~20 px
        # glyph height, common in phone photos of forms.
        short_edge = min(gray.width, gray.height)
        if 0 < short_edge < _MIN_EDGE_FOR_OCR:
            scale = _MIN_EDGE_FOR_OCR / short_edge
            gray = gray.resize(
                (round(gray.width * scale), round(gray.height * scale)),
                Image.BICUBIC,
            )

        try:
            text, confidence, words = self._run(gray, psm=None)
            # A dire first pass on a non-blank image means the page defeated
            # the default settings — climb a bounded rescue ladder: sparse
            # segmentation, median denoise, then small-angle deskew. Each
            # rung keeps the best result; stop as soon as one reads cleanly.
            if confidence < _RETRY_CONFIDENCE and words > 0:
                denoised = gray.filter(ImageFilter.MedianFilter(3))
                ladder: list[tuple[Image.Image, int | None]] = [
                    (gray, 11),        # sparse text mode
                    (denoised, None),  # salt-and-pepper noise removed
                    (denoised, 11),
                ]
                ladder += [
                    (gray.rotate(angle, expand=True, fillcolor=255), None)
                    for angle in _DESKEW_ANGLES
                ]
                for candidate_image, psm in ladder:
                    retry_text, retry_conf, retry_words = self._run(
                        candidate_image, psm=psm
                    )
                    if retry_conf > confidence:
                        text, confidence, words = retry_text, retry_conf, retry_words
                    if confidence >= _GOOD_ENOUGH:
                        break
        except OCRFailedError:
            raise
        except Exception as exc:
            raise OCRFailedError(str(exc)) from exc

        return RecognizedText(
            text=text,
            confidence=round(confidence, 4),
            word_count=words,
            rotation_applied=rotation,
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _auto_orient(self, image: Image.Image) -> tuple[Image.Image, int]:
        """
        Detect and undo page rotation using Tesseract's OSD pass.

        Rotation is applied only when OSD is CONFIDENT (its own confidence
        score) — 180° false positives on busy forms are common at low
        confidence, and rotating an upright page destroys recognition. When
        OSD fails entirely (blank/tiny images) we proceed unrotated.
        """
        try:
            osd = pytesseract.image_to_osd(image)
            rotate = re.search(r"Rotate: (\d+)", osd)
            conf = re.search(r"Orientation confidence: ([\d.]+)", osd)
            rotation = int(rotate.group(1)) if rotate else 0
            confidence = float(conf.group(1)) if conf else 0.0
        except Exception:
            return image, 0
        if rotation in (90, 180, 270) and confidence >= _OSD_MIN_CONFIDENCE:
            # PIL rotates counter-clockwise; OSD reports the clockwise fix.
            return image.rotate(-rotation, expand=True), rotation
        return image, 0

    def _run(self, image: Image.Image, psm: int | None) -> tuple[str, float, int]:
        """
        One recognition pass returning (text, mean word confidence 0-1, words).

        Uses image_to_data so every word carries its own confidence; the mean
        over real words (conf >= 0) is the page confidence. No words = blank
        page = ("", 0.0, 0).
        """
        config = f"--psm {psm}" if psm is not None else ""
        data = pytesseract.image_to_data(
            image,
            lang=self._languages,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
        words: list[str] = []
        confidences: list[float] = []
        for word, conf in zip(data["text"], data["conf"]):
            word = word.strip()
            if not word:
                continue
            conf = float(conf)
            if conf < 0:  # -1 marks layout blocks, not real words
                continue
            words.append(word)
            confidences.append(conf)

        if not words:
            return "", 0.0, 0

        # Rebuild line structure from the data table so downstream label
        # matching ("PAN : ABCDE1234F") sees words in their visual lines.
        lines: dict[tuple[int, int, int], list[str]] = {}
        for i, word in enumerate(data["text"]):
            word = word.strip()
            if not word or float(data["conf"][i]) < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(word)
        text = "\n".join(" ".join(ws) for ws in lines.values())

        mean_confidence = sum(confidences) / len(confidences) / 100.0
        return text, mean_confidence, len(words)
