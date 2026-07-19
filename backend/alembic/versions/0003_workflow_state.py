"""Deployment: workflow state tables (sessions, documents, profiles, PDFs, assets, transcript).

These tables were introduced with the SQLite workflow repositories and had only
ever been created by `create_all` at startup. That is fine for a local file
database and wrong for a managed one, where the schema must be reproducible and
versioned — so they get a real migration here before the first production
deploy.

`kyc_session_assets` and `kyc_conversation_turns` are new: their in-memory
predecessors lost photograph/signature metadata and the interview transcript on
every restart.

Revision ID: 0003_workflow_state
Revises: 0002_upload_history
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_workflow_state"
down_revision = "0002_upload_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kyc_sessions",
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=32), nullable=True, index=True),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "kyc_documents",
        sa.Column("document_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=32), nullable=True, index=True),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "kyc_profiles",
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "kyc_generated_pdfs",
        sa.Column("pdf_id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    # One asset per (session, kind): the composite key is what makes a second
    # upload of the same kind replace the first instead of accumulating.
    op.create_table(
        "kyc_session_assets",
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("kind", sa.String(length=16), primary_key=True),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "kyc_conversation_turns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_kyc_conversation_turns_session_position",
        "kyc_conversation_turns",
        ["session_id", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_kyc_conversation_turns_session_position",
        table_name="kyc_conversation_turns",
    )
    op.drop_table("kyc_conversation_turns")
    op.drop_table("kyc_session_assets")
    op.drop_table("kyc_generated_pdfs")
    op.drop_table("kyc_profiles")
    op.drop_table("kyc_documents")
    op.drop_table("kyc_sessions")
