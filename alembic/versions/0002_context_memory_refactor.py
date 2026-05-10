"""context_memory_refactor: new tables, chat_sessions schema change, drop interview_states

Revision ID: 0002_context_memory_refactor
Revises: 0001_initial_schema
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_context_memory_refactor"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. New tables ─────────────────────────────────────────────────

    op.create_table(
        "interview_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("audio_upload_id", sa.String(), nullable=True),
        sa.Column("resume_upload_id", sa.String(), nullable=True),
        sa.Column("jd_upload_id", sa.String(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("analysis_json", sa.Text(), nullable=True),
        sa.Column("interview_plan", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_interview_records_id", "interview_records", ["id"])
    op.create_index("ix_interview_records_user_id", "interview_records", ["user_id"])
    op.create_index("ix_interview_records_status", "interview_records", ["status"])

    op.create_table(
        "resume_sections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("upload_id", sa.String(), nullable=False),
        sa.Column("section_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("embedding_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_resume_sections_id", "resume_sections", ["id"])
    op.create_index("ix_resume_sections_user_id", "resume_sections", ["user_id"])
    op.create_index("ix_resume_sections_upload_id", "resume_sections", ["upload_id"])
    op.create_index("ix_resume_sections_section_type", "resume_sections", ["section_type"])

    # ── 2. chat_sessions: add new columns, rename working_state → session_state ──

    op.add_column(
        "chat_sessions",
        sa.Column("session_type", sa.String(), server_default="general", nullable=False),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("interview_id", sa.String(), sa.ForeignKey("interview_records.id"), nullable=True),
    )
    op.add_column(
        "chat_sessions",
        sa.Column("session_state", sa.Text(), nullable=True),
    )
    op.create_index("ix_chat_sessions_session_type", "chat_sessions", ["session_type"])
    op.create_index("ix_chat_sessions_interview_id", "chat_sessions", ["interview_id"])

    # Copy working_state data to session_state
    op.execute("UPDATE chat_sessions SET session_state = working_state WHERE working_state IS NOT NULL")

    # Drop old columns
    op.drop_column("chat_sessions", "working_state")
    op.drop_column("chat_sessions", "memory_cursor")

    # ── 3. Drop interview_states table ────────────────────────────────

    op.drop_table("interview_states")


def downgrade() -> None:
    # Recreate interview_states
    op.create_table(
        "interview_states",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("session_id", "user_id", name="uq_interview_states_session_user"),
    )
    op.create_index("ix_interview_states_session_id", "interview_states", ["session_id"])
    op.create_index("ix_interview_states_user_id", "interview_states", ["user_id"])

    # Restore chat_sessions columns
    op.add_column("chat_sessions", sa.Column("memory_cursor", sa.Integer(), nullable=True))
    op.add_column("chat_sessions", sa.Column("working_state", sa.Text(), nullable=True))
    op.execute("UPDATE chat_sessions SET working_state = session_state WHERE session_state IS NOT NULL")
    op.drop_index("ix_chat_sessions_interview_id", "chat_sessions")
    op.drop_index("ix_chat_sessions_session_type", "chat_sessions")
    op.drop_column("chat_sessions", "session_state")
    op.drop_column("chat_sessions", "interview_id")
    op.drop_column("chat_sessions", "session_type")

    # Drop new tables
    op.drop_table("resume_sections")
    op.drop_table("interview_records")
