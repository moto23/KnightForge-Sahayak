"""Phase 13: persistent upload history.

Revision ID: 0002_upload_history
Revises: 0001_initial
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_upload_history"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_history",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("detected_type", sa.String(length=80), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("ocr_status", sa.String(length=16), nullable=False),
        sa.Column("processing_status", sa.String(length=16), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_upload_history_user_id", "upload_history", ["user_id"])
    op.create_index("ix_upload_history_document_id", "upload_history", ["document_id"])
    op.create_index("ix_upload_history_uploaded_at", "upload_history", ["uploaded_at"])


def downgrade() -> None:
    op.drop_table("upload_history")
