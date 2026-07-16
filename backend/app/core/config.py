"""
Application settings.

Centralizes ALL configuration in one typed object so the rest of the code never
reads os.environ directly. Values are loaded (in priority order) from real
environment variables, then a local `.env` file, then the defaults below.

Powered by pydantic-settings, so every value is validated and type-cast on
startup — a bad config fails fast and loudly instead of at request time.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- App metadata (surfaced in Swagger / OpenAPI docs) ---
    APP_NAME: str = "KnightForge Sahayak API"
    APP_DESCRIPTION: str = "AI Paperwork Copilot — backend API"
    APP_VERSION: str = "0.1.0"

    # --- Runtime ---
    # ENVIRONMENT drives environment-specific behavior (e.g. docs visibility).
    ENVIRONMENT: str = "development"
    # DEBUG toggles verbose logging and auto-reload-friendly behavior.
    DEBUG: bool = True
    # LOG_LEVEL is any standard logging level name: DEBUG/INFO/WARNING/ERROR.
    LOG_LEVEL: str = "INFO"

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # --- CORS ---
    # Comma-separated list of origins allowed to call this API from a browser.
    # Kept permissive for local dev; tighten for production.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # --- OpenAI (Phase 5 — AI Conversation Engine) ---
    # Empty key = AI disabled; every conversation endpoint then serves the
    # deterministic fallback responses instead of failing.
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    # Per-request timeout: a hung OpenAI call must never hang the interview.
    OPENAI_TIMEOUT_SECONDS: float = 20.0

    # --- Uploads (Phase 6 — Document Upload Pipeline) ---
    # Root directory for stored uploads, relative to the backend working
    # directory (subfolders pdf/ and images/ are created beneath it).
    UPLOAD_DIR: str = "uploads"
    # Hard cap on a single uploaded file. Enforced while streaming, so an
    # oversized body is rejected without ever being fully read into memory.
    MAX_UPLOAD_SIZE_MB: int = 10

    # --- Document Understanding (Phase 7 — OCR & Extraction Pipeline) ---
    # Full path to the tesseract executable. Empty = auto-detect (PATH, then
    # the standard Windows install locations). Never imported outside the
    # TesseractOCRProvider adapter.
    TESSERACT_CMD: str = ""
    # Language(s) Tesseract should recognize ("eng", "eng+hin", ...).
    OCR_LANGUAGES: str = "eng"
    # DPI used when rasterizing scanned-PDF pages for OCR. 300 is the sweet
    # spot for Tesseract accuracy vs. speed.
    OCR_RENDER_DPI: int = 300
    # A PDF page counts as having a usable embedded text layer only if it
    # yields at least this many characters (guards against near-empty layers).
    PDF_TEXT_LAYER_MIN_CHARS: int = 50
    # Minimum confidence (0.0-1.0) an extracted field needs before the
    # SessionPrefillService will auto-fill it into an interview session.
    # Uncertain fields stay unanswered so the interview asks about them.
    PREFILL_CONFIDENCE_THRESHOLD: float = 0.75

    # Load a local `.env` file if present. `extra="ignore"` means placeholder
    # keys reserved for later phases (OpenAI, OCR, etc.) won't crash startup.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Split the CORS_ORIGINS string into a clean list for the middleware."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.

    @lru_cache ensures the `.env` file is parsed exactly once per process and the
    same object is reused everywhere it's imported.
    """
    return Settings()


# Convenience singleton for simple imports: `from app.core.config import settings`.
settings = get_settings()
