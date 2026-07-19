"""
Application settings.

Centralizes ALL configuration in one typed object so the rest of the code never
reads os.environ directly. Values are loaded (in priority order) from real
environment variables, then a local `.env` file, then the defaults below.

Powered by pydantic-settings, so every value is validated and type-cast on
startup — a bad config fails fast and loudly instead of at request time.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# The shipped development secret. Named so the production guard below can
# recognise it; never use it outside local work.
_INSECURE_JWT_DEFAULT = "dev-only-secret-change-me"


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

    # --- Google Gemini (Phase 5 — AI Conversation Engine) ---
    # The AIService now runs on the Google GenAI SDK (google-genai).
    # Empty key = AI disabled; every AI-phrased endpoint then serves its
    # deterministic fallback responses instead of failing.
    GEMINI_API_KEY: str = ""
    # Flash-lite carries a far larger free-tier daily allowance than the
    # full Flash models (which cap at ~20 requests/day/model and are quickly
    # exhausted by document extraction), so the assistant keeps working.
    # "-latest" tracks the current supported release rather than pinning a
    # model that will eventually be retired.
    GEMINI_MODEL: str = "gemini-flash-lite-latest"
    # Per-request timeout: a hung Gemini call must never hang the interview.
    GEMINI_TIMEOUT_SECONDS: float = 20.0

    # --- Legacy OpenAI fields (retained for compatibility) ---
    # No longer used to reach OpenAI. OPENAI_MODEL survives because existing
    # modules label AI output with it (e.g. the Knowledge RAG `generator`
    # field); it is mirrored from GEMINI_MODEL below unless explicitly set.
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = ""
    OPENAI_TIMEOUT_SECONDS: float = 20.0

    @model_validator(mode="after")
    def _mirror_active_ai_model(self) -> "Settings":
        """Keep the legacy OPENAI_MODEL label pointing at the ACTIVE model."""
        if not self.OPENAI_MODEL:
            self.OPENAI_MODEL = self.GEMINI_MODEL
        return self

    # --- Uploads (Phase 6 — Document Upload Pipeline) ---
    # Root directory for stored uploads, relative to the backend working
    # directory (subfolders pdf/ and images/ are created beneath it).
    UPLOAD_DIR: str = "uploads"
    # Where uploaded documents, photos/signatures and generated PDFs live.
    #   "local" -> LocalStorageAdapter under UPLOAD_DIR (development)
    #   "s3"    -> S3StorageAdapter against a PRIVATE S3-compatible bucket
    #
    # Free hosting tiers have an ephemeral filesystem, so "local" there means
    # every redeploy silently orphans every stored document while the database
    # still points at it. Production must set "s3".
    STORAGE_BACKEND: str = "local"
    STORAGE_BUCKET: str = ""
    STORAGE_ENDPOINT_URL: str = ""
    STORAGE_ACCESS_KEY_ID: str = ""
    STORAGE_SECRET_ACCESS_KEY: str = ""
    STORAGE_REGION: str = "auto"
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

    # Minimum confidence a MERGED canonical value needs before the Universal
    # Document Intelligence pipeline writes it into the interview session.
    #
    # Deliberately far below PREFILL_CONFIDENCE_THRESHOLD: merged values have
    # already passed the deterministic Validation Engine, which is the real
    # gatekeeper. Real-world OCR pages score ~0.65-0.75, so gating validated
    # values at 0.75 silently dropped almost everything the pipeline read —
    # the interview then re-asked fields the profile had already resolved.
    # A value that FAILS validation is capped at 0.35 by the ConfidenceEngine,
    # so this floor only rejects dire noise, never good data.
    CANONICAL_APPLY_MIN_CONFIDENCE: float = 0.40

    # --- PDF Generation (Phase 8 — Smart PDF Generation Engine) ---
    # The blank KYC form the overlay is painted onto (relative to backend/).
    PDF_TEMPLATE_PATH: str = "../samples/sample-kyc.pdf"
    # External JSON mapping field_id -> page/x/y. NEVER hardcode coordinates
    # in Python — edit this file to recalibrate.
    PDF_COORDINATE_MAP_PATH: str = "templates/kyc_coordinate_map.json"
    # Output directory for generated PDFs (UUID filenames, never overwritten).
    GENERATED_PDF_DIR: str = "generated_pdfs"

    # --- Knowledge RAG Engine (Phase 10) ---
    # Directory of official KYC reference documents to ingest (.md/.txt/.pdf),
    # relative to the backend working directory.
    # Timezone the assistant states when answering date/time questions. The
    # user's own zone is never guessed — the answer names this one explicitly.
    APP_TIMEZONE: str = "Asia/Kolkata"

    # Which EmbeddingProvider adapter backs Knowledge Chat retrieval.
    #   "onnx"  -> OnnxEmbedder (all-MiniLM-L6-v2 on ONNX Runtime, ~215 MB)
    #   "torch" -> SentenceTransformerEmbedder (bge-small-en-v1.5, ~512 MB)
    #
    # Defaults to "onnx" because the torch path costs ~300 MB more and pushed
    # the backend to a measured 658 MB peak — above the 512 MB ceiling of the
    # free hosting tier this deploys to. Retrieval quality was benchmarked
    # across both before this default was chosen.
    #
    # NOTE: the two adapters produce vectors in DIFFERENT spaces. Changing
    # this value REQUIRES re-ingesting the knowledge corpus; a mixed index
    # returns meaningless neighbours.
    KNOWLEDGE_EMBEDDER: str = "onnx"

    KNOWLEDGE_DOCS_DIR: str = "knowledge_docs"
    # On-disk home of the ChromaDB vector database (persists across restarts).
    KNOWLEDGE_DB_DIR: str = "knowledge_db"
    # Chroma collection name holding the KYC knowledge chunks.
    KNOWLEDGE_COLLECTION: str = "kyc_knowledge"
    # Local SentenceTransformer embedding model. bge-small-en-v1.5 tops the
    # small-model MTEB retrieval charts; all-MiniLM-L6-v2 is a lighter fallback.
    KNOWLEDGE_EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    # Semantic chunking: paragraph-packed chunks capped at this many characters…
    KNOWLEDGE_CHUNK_SIZE: int = 900
    # …with this much tail carried into the next chunk so no fact is cut in half.
    KNOWLEDGE_CHUNK_OVERLAP: int = 150
    # How many chunks retrieval returns to the generator.
    KNOWLEDGE_TOP_K: int = 5
    # Cosine-similarity floor: chunks below this are discarded outright.
    # NOTE: similarity alone is a weak signal — bge cosine scores for totally
    # unrelated text can reach ~0.5 — so this floor is only the first layer
    # of the confidence gate (see KnowledgeService.query).
    # Calibrated for the ACTIVE embedding model (KNOWLEDGE_EMBEDDER).
    # Cosine scores are not comparable across models, so these move together
    # with the embedder. Measured on the KYC corpus:
    #
    #                    in-domain KYC      off-topic
    #   bge-small           0.68 - 0.80     up to ~0.50 (per the note above)
    #   all-MiniLM-L6-v2    0.31 - 0.61     0.00 - 0.16
    #
    # MiniLM compresses the scale but separates the two classes far more
    # cleanly, so the floor sits between the highest off-topic score (0.154)
    # and the lowest genuine KYC score (0.312) with margin on both sides.
    # Leaving the bge value of 0.35 here would have silently refused real
    # questions like "Do I need a photo on the SBI form?".
    KNOWLEDGE_MIN_SIMILARITY: float = 0.25
    # Second gate layer: a retrieved context must either be VERY similar…
    # Scaled with the floor above: 0.62 sat near the top of bge's range, and
    # the equivalent point on MiniLM's compressed range is ~0.45.
    KNOWLEDGE_STRONG_SIMILARITY: float = 0.45
    # …or share at least this fraction of the question's content terms
    # (lexical grounding). Below both -> honest "I don't know", no LLM call.
    KNOWLEDGE_MIN_TERM_OVERLAP: float = 0.25

    # --- Universal Document Intelligence (Phase 11) ---
    # Directory of document-schema JSON files (one per supported form/document,
    # e.g. cvl.json, sbi.json, pan.json), relative to the backend working
    # directory. Schemas define OCR labels, aliases, canonical mappings and
    # classification markers — mappings NEVER live in Python business logic.
    FORM_LAYOUTS_DIR: str = "form_layouts"
    DOCUMENT_SCHEMAS_DIR: str = "schemas"

    # --- Auth + persistence (Phase 12) ---
    # SQLite database for users, refresh tokens and saved chats. Relative to
    # the backend working directory; swap for postgres:// in production.
    DATABASE_URL: str = "sqlite:///./app.db"
    # HMAC secret for signing JWT access tokens. The default is fine for local
    # dev only — ALWAYS override via .env in any shared environment.
    JWT_SECRET: str = _INSECURE_JWT_DEFAULT
    JWT_ALGORITHM: str = "HS256"
    # Short-lived access token (sent as a Bearer header, kept in JS memory).
    ACCESS_TOKEN_MINUTES: int = 30
    # Long-lived refresh token (HttpOnly cookie, rotated on every use).
    REFRESH_TOKEN_DAYS: int = 14
    AUTH_COOKIE_NAME: str = "kf_refresh"
    # Set true when serving over HTTPS so the refresh cookie is Secure.
    AUTH_COOKIE_SECURE: bool = False
    # --- Google OAuth (empty = the Google button is hidden/disabled) ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/google/callback"
    # Where the OAuth callback sends the browser after a successful login.
    FRONTEND_URL: str = "http://localhost:3000"

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

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> "Settings":
        """
        Refuse to BOOT a production process that is configured unsafely.

        These are the settings whose defaults are deliberately convenient for
        local work and dangerous in the open: a shipped JWT secret lets anyone
        mint a token for any account, and CORS "*" hands a hostile page the
        applicant's KYC data through the browser. A warning in a log is not
        enough — nobody reads the log of a service that started fine — so the
        process refuses to come up instead.

        Development is untouched: every check is inert unless ENVIRONMENT says
        production.
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.JWT_SECRET == _INSECURE_JWT_DEFAULT:
            problems.append(
                "JWT_SECRET is still the shipped development value; set a "
                "unique random secret."
            )
        if len(self.JWT_SECRET.encode()) < 32:
            problems.append(
                "JWT_SECRET must be at least 32 bytes "
                f"(currently {len(self.JWT_SECRET.encode())})."
            )
        if self.DEBUG:
            problems.append("DEBUG must be False in production.")
        if "*" in self.cors_origins_list:
            problems.append("CORS_ORIGINS must name the deployed frontend, not '*'.")
        if any(o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o
               for o in self.cors_origins_list):
            problems.append("CORS_ORIGINS must use https:// for non-local origins.")
        # Durability. Production runs on an ephemeral filesystem, so these two
        # defaults do not fail loudly — they lose applicant data quietly at the
        # next redeploy, with the database still referencing the missing files.
        if self.DATABASE_URL.startswith("sqlite"):
            problems.append(
                "DATABASE_URL must point at managed PostgreSQL in production; "
                "SQLite lives on an ephemeral disk and is lost on redeploy."
            )
        if self.STORAGE_BACKEND.strip().lower() != "s3":
            problems.append(
                "STORAGE_BACKEND must be 's3' in production; local storage is "
                "lost on redeploy, orphaning every stored document."
            )
        elif not (self.STORAGE_BUCKET and self.STORAGE_ENDPOINT_URL
                  and self.STORAGE_ACCESS_KEY_ID and self.STORAGE_SECRET_ACCESS_KEY):
            problems.append(
                "STORAGE_BACKEND='s3' requires STORAGE_BUCKET, "
                "STORAGE_ENDPOINT_URL, STORAGE_ACCESS_KEY_ID and "
                "STORAGE_SECRET_ACCESS_KEY."
            )

        if problems:
            raise ValueError(
                "Unsafe production configuration:\n  - " + "\n  - ".join(problems)
            )
        return self


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
