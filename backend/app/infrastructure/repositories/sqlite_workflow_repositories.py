"""
SQLite-backed adapters for the workflow state that must survive a restart.

Each class implements the SAME repository interface its in-memory predecessor
did, so services, routes and ownership checks are untouched — only the binding
in `dependencies.py` changes.

Storage shape: the domain object is a pydantic model, serialised whole into a
`data_json` column, beside the handful of columns that must be queryable
(`owner_id`, and a PDF's `session_id`, both of which the ownership checks read).
Keeping the payload opaque means there is no field-by-field mapping to drift
out of step with the domain, and adding a domain field later needs no
migration.

Each call opens and closes its own short SQLAlchemy session. These adapters are
process-wide singletons shared by concurrent requests, so they cannot hold one
long-lived DB session; a request-scoped one would also outlive the object here.
A row that fails to deserialise (a domain model changed shape under stored
data) is treated as ABSENT rather than raising, so one stale row cannot take
the API down — the workflow restarts instead.
"""

import logging

from sqlalchemy import select

from app.domain.document import UploadedDocument
from app.domain.intelligence import ProfileRepository, ProfileState
from app.domain.pdf import GeneratedPdf
from app.domain.repositories import (
    DocumentRepository,
    GeneratedPdfRepository,
    SessionRepository,
)
from app.domain.session import Session
from app.infrastructure.db.database import SessionLocal
from app.infrastructure.db.models import (
    DocumentRecord,
    GeneratedPdfRecord,
    ProfileRecord,
    SessionRecord,
)

logger = logging.getLogger(__name__)


def _load(model, raw: str, what: str):
    """Deserialise a stored payload, or None when it no longer fits the model."""
    try:
        return model.model_validate_json(raw)
    except Exception:  # noqa: BLE001 - a stale row must not break the API
        logger.warning("Discarding unreadable stored %s", what)
        return None


class SqliteSessionRepository(SessionRepository):
    """Interview sessions, with the owner column the ownership checks read."""

    def add(self, session: Session) -> None:
        self.save(session)

    def get(self, session_id: str) -> Session | None:
        with SessionLocal() as db:
            row = db.get(SessionRecord, session_id)
            return _load(Session, row.data_json, "session") if row else None

    def save(self, session: Session) -> None:
        with SessionLocal() as db:
            row = db.get(SessionRecord, session.session_id)
            if row is None:
                row = SessionRecord(session_id=session.session_id)
                db.add(row)
            row.owner_id = session.owner_id
            row.data_json = session.model_dump_json()
            db.commit()

    def delete(self, session_id: str) -> bool:
        with SessionLocal() as db:
            row = db.get(SessionRecord, session_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True


class SqliteDocumentRepository(DocumentRepository):
    """Uploaded-document metadata (file bytes remain the FileStorage port's)."""

    def add(self, document: UploadedDocument) -> None:
        with SessionLocal() as db:
            if db.get(DocumentRecord, document.document_id) is None:
                db.add(
                    DocumentRecord(
                        document_id=document.document_id,
                        owner_id=getattr(document, "owner_id", None),
                        data_json=document.model_dump_json(),
                    )
                )
                db.commit()

    def get(self, document_id: str) -> UploadedDocument | None:
        with SessionLocal() as db:
            row = db.get(DocumentRecord, document_id)
            return _load(UploadedDocument, row.data_json, "document") if row else None

    def list_all(self) -> tuple[UploadedDocument, ...]:
        with SessionLocal() as db:
            rows = db.scalars(
                select(DocumentRecord).order_by(DocumentRecord.created_at.desc())
            ).all()
        loaded = (_load(UploadedDocument, r.data_json, "document") for r in rows)
        return tuple(doc for doc in loaded if doc is not None)

    def delete(self, document_id: str) -> bool:
        with SessionLocal() as db:
            row = db.get(DocumentRecord, document_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True


class SqliteProfileRepository(ProfileRepository):
    """The merged canonical profile and its evidence, per session."""

    def get(self, session_id: str) -> ProfileState | None:
        with SessionLocal() as db:
            row = db.get(ProfileRecord, session_id)
            return _load(ProfileState, row.data_json, "profile") if row else None

    def save(self, state: ProfileState) -> None:
        with SessionLocal() as db:
            row = db.get(ProfileRecord, state.session_id)
            if row is None:
                row = ProfileRecord(session_id=state.session_id)
                db.add(row)
            row.data_json = state.model_dump_json()
            db.commit()

    def delete(self, session_id: str) -> bool:
        with SessionLocal() as db:
            row = db.get(ProfileRecord, session_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True


class SqliteGeneratedPdfRepository(GeneratedPdfRepository):
    """Generated-PDF metadata; ownership resolves through `generated_by_session`."""

    def add(self, record: GeneratedPdf) -> None:
        with SessionLocal() as db:
            if db.get(GeneratedPdfRecord, record.pdf_id) is None:
                db.add(
                    GeneratedPdfRecord(
                        pdf_id=record.pdf_id,
                        session_id=record.generated_by_session,
                        data_json=record.model_dump_json(),
                    )
                )
                db.commit()

    def get(self, pdf_id: str) -> GeneratedPdf | None:
        with SessionLocal() as db:
            row = db.get(GeneratedPdfRecord, pdf_id)
            return _load(GeneratedPdf, row.data_json, "generated PDF") if row else None

    def list_all(self) -> tuple[GeneratedPdf, ...]:
        with SessionLocal() as db:
            rows = db.scalars(
                select(GeneratedPdfRecord).order_by(GeneratedPdfRecord.created_at.desc())
            ).all()
        loaded = (_load(GeneratedPdf, r.data_json, "generated PDF") for r in rows)
        return tuple(pdf for pdf in loaded if pdf is not None)

    def delete(self, pdf_id: str) -> bool:
        with SessionLocal() as db:
            row = db.get(GeneratedPdfRecord, pdf_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True
