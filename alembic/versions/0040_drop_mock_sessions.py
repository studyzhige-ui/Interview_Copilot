"""CLEANUP: drop the deprecated ``mock_interview_sessions`` table.

The mock interview's live runtime moved to ``mock_interview_runtime`` and its
structured QA is parsed from ``conversation_messages`` into ``interview_qa``
(CONVERSATION-MOCK). After that rewrite nothing reads or writes
``mock_interview_sessions`` — it was retained only as a migration-era archive
table. CLEANUP drops it (RFC §10.3 "删除废弃表").

Revision ID: 0040_drop_mock_sessions
Revises: 0039_drop_personal_memory
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0040_drop_mock_sessions"
down_revision: Union[str, None] = "0039_drop_personal_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "mock_interview_sessions" in inspect(bind).get_table_names():
        # drop_table cascades the table's FKs + indexes on Postgres.
        op.drop_table("mock_interview_sessions")


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if "mock_interview_sessions" in inspect(bind).get_table_names():
        return
    op.create_table(
        "mock_interview_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "interview_record_id", sa.String(),
            sa.ForeignKey("interview_records.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="in_progress"),
        sa.Column("current_phase", sa.String(), nullable=True),
        sa.Column("current_question_idx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qa_buffer_json", sa.Text(), nullable=True),
        sa.Column("plan_snapshot_json", sa.Text(), nullable=True),
        sa.Column("interviewer_style", sa.String(), nullable=False, server_default="professional"),
        sa.Column("voice_mode", sa.String(), nullable=False, server_default="hybrid"),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    if not is_sqlite:
        op.create_index(
            "ix_mock_interview_sessions_user_id", "mock_interview_sessions", ["user_id"],
        )
        op.create_index(
            "ix_mock_interview_sessions_interview_record_id",
            "mock_interview_sessions", ["interview_record_id"],
        )
        op.create_index(
            "ix_mock_interview_sessions_status", "mock_interview_sessions", ["status"],
        )
