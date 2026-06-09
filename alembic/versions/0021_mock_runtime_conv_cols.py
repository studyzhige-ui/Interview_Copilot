"""CONVERSATION-MOCK (schema foundation): mock_interview_runtime + conversation cols.

Adds the live mock-interview runtime table (supersedes
``chat_sessions.mock_interview_state`` + the ``mock_interview_sessions`` archive
as the runtime store) and the ``mode`` / ``subject_type`` / ``subject_id``
columns on ``chat_sessions`` (the conversation model).

The pervasive ``chat_sessions``→``conversations`` table rename, the Runtime
Director v6 removal, and the atomic mock-start rewrite are sequenced as a
follow-up (tracked in CLEANUP) since they couple to the in-flight context-
management code.

Revision ID: 0021_mock_runtime_conv_cols
Revises: 0020_document_chunks
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0021_mock_runtime_conv_cols"
down_revision: Union[str, None] = "0020_document_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, col: str) -> bool:
    return _has_table(insp, table) and col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _has_table(insp, "mock_interview_runtime"):
        op.create_table(
            "mock_interview_runtime",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False, index=True),
            sa.Column(
                "interview_record_id", sa.String(),
                sa.ForeignKey("interview_records.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column(
                "conversation_id", sa.String(),
                sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=True,
            ),
            sa.Column("status", sa.String(), nullable=False, server_default="in_progress", index=True),
            sa.Column("current_stage_key", sa.String(), nullable=True),
            sa.Column("stage_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_question_text", sa.Text(), nullable=True),
            sa.Column("current_question_message_id", sa.Integer(), nullable=True),
            sa.Column("plan_json", sa.Text(), nullable=True),
            sa.Column("plan_template_key", sa.String(), nullable=False, server_default="general"),
            sa.Column("interviewer_style", sa.String(), nullable=False, server_default="professional"),
            sa.Column("voice_mode", sa.String(), nullable=False, server_default="hybrid"),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("last_activity_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_mock_runtime_user_status", "mock_interview_runtime", ["user_id", "status"])

    if not _has_column(insp, "chat_sessions", "mode"):
        op.add_column("chat_sessions", sa.Column("mode", sa.String(), nullable=False, server_default="chat"))
    if not _has_column(insp, "chat_sessions", "subject_type"):
        op.add_column("chat_sessions", sa.Column("subject_type", sa.String(), nullable=True))
    if not _has_column(insp, "chat_sessions", "subject_id"):
        op.add_column("chat_sessions", sa.Column("subject_id", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    for col in ("subject_id", "subject_type", "mode"):
        if _has_column(insp, "chat_sessions", col):
            op.drop_column("chat_sessions", col)
    if _has_table(insp, "mock_interview_runtime"):
        op.drop_table("mock_interview_runtime")
