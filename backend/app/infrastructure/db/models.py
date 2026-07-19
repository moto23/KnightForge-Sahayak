"""
ORM models (Phase 12) — users, refresh tokens, saved conversations.

SQLAlchemy 2.x typed declarative style. Four tables:

    users               account identity (password and/or Google)
    refresh_tokens      one row per issued refresh token (hash only), enabling
                        rotation, revocation and reuse detection
    chat_conversations  a saved Knowledge Assistant conversation
    chat_messages       its turns, with the RAG citations preserved as JSON

Ownership is structural: conversations/messages hang off user_id and every
query in ChatService filters by it — a foreign user's chat id yields 404.
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.database import Base


def _uuid() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    # Null for Google-only accounts (no password ever set).
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # Google's stable subject id — set once the account is linked to Google.
    google_sub: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["ChatConversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # SHA-256 of the cookie value; the raw token never touches the database.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Rotation marks the old row revoked; presenting a revoked token again is
    # reuse (theft signal) and revokes the user's every token.
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, index=True
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class UploadHistory(Base):
    """One row per uploaded document (Phase 13) — survives restarts.

    user_id is NULL for guest uploads; the /upload/history endpoint only ever
    lists the caller's own rows. The row outlives the physical file: deleting
    a document flips processing_status to "deleted" instead of erasing the
    audit trail.
    """

    __tablename__ = "upload_history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # UUID of the stored document (in-memory/document store id).
    document_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # User-selected type BEFORE upload (kyc_form, pan_card, aadhaar_card, ...).
    document_type: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    # AI-detected type label (Phase 11 classifier), once known.
    detected_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pending | completed | failed
    ocr_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # uploaded | analyzed | prefilled | deleted
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploaded")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Assistant-only RAG metadata, serialized JSON (citations list, etc.).
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confident: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    generator: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")


# Search + listing hit these together constantly.
Index("ix_chat_messages_convo_created", ChatMessage.conversation_id, ChatMessage.created_at)


# --------------------------------------------------------------------------- #
# Workflow state (Phase 19 persistence).
#
# These four tables exist so a backend restart does not destroy a KYC workflow.
# Everything below used to live in process memory, which meant every code
# reload wiped the session, its documents, its merged profile and its generated
# PDFs — the frontend then found a dead session id, discarded it, and started a
# fresh one that fell back to the default form scope ("0%, 21 required
# fields").
#
# The domain objects are pydantic models, so each row stores the object as JSON
# in `data_json` alongside the few columns that must be QUERYABLE (owner, and
# the session a PDF belongs to, both used by the ownership checks). Keeping the
# payload opaque means no field-by-field mapping to drift out of sync with the
# domain, and adding a domain field later needs no migration.
# --------------------------------------------------------------------------- #


class SessionRecord(Base):
    """One interview session, owner included (NULL = guest)."""

    __tablename__ = "kyc_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class DocumentRecord(Base):
    """Uploaded-document METADATA. Bytes stay with the FileStorage adapter."""

    __tablename__ = "kyc_documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProfileRecord(Base):
    """The merged canonical profile + evidence for one session."""

    __tablename__ = "kyc_profiles"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class GeneratedPdfRecord(Base):
    """Generated-PDF metadata; `session_id` is what its ownership resolves through."""

    __tablename__ = "kyc_generated_pdfs"

    pdf_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SessionAssetRecord(Base):
    """
    Photograph/signature METADATA for one session. Bytes stay with FileStorage.

    Previously in-memory, which was a latent bug rather than a design choice:
    the image bytes persisted but the record pointing at them did not, so after
    a restart a session reported its photo missing while the file sat in
    storage — re-uploads, a wrong Progress figure and orphaned objects.

    A session holds at most ONE asset per kind, enforced here by the composite
    primary key so a second upload replaces the first rather than accumulating.
    """

    __tablename__ = "kyc_session_assets"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ConversationTurnRecord(Base):
    """
    One utterance of an interview transcript, ordered by `position`.

    Turns are append-only and must come back in the order they were spoken, so
    ordering is an explicit column rather than an accident of insertion order.
    The answers themselves live on the Session; losing these would not corrupt
    the workflow, but the visible conversation would silently empty on restart.
    """

    __tablename__ = "kyc_conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_kyc_conversation_turns_session_position", "session_id", "position"),
    )
