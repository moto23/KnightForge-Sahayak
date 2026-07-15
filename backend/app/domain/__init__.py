# `domain` package: the pure business core of the application.
#
# Contains the KYC form's structured metadata, enums, domain models, the schema
# registry, and (from Phase 4) deterministic validators. This layer has ZERO
# dependencies on FastAPI, the database, OpenAI, OCR, or PDF tooling — it is
# plain, fully unit-testable Python and is the single source of truth for what
# the KYC form *is*.
