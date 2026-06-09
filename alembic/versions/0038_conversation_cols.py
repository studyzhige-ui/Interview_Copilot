"""CONVERSATION-MOCK (part B): conversations/conversation_messages column
reshape to the target schema.

- conversations: rename ``session_type`` -> ``type``; drop the legacy
  ``interview_id`` column (subject binding now lives in ``subject_type`` /
  ``subject_id``) and the ``mock_interview_state`` JSON blob (the live mock
  runtime moves into ``mock_interview_runtime``).
- conversation_messages: rename ``session_id`` -> ``conversation_id``; add the
  optional ``tool_call_id`` / ``tool_name`` pairing helpers for tool messages.

On Postgres ``RENAME COLUMN`` auto-updates dependent index/constraint/FK column
references; the index + unique-constraint *names* are renamed explicitly to
match. The single-column ``interview_id`` index is dropped together with its
column. The composite ``ix_conversations_user_type_arch`` keeps its name (its
``session_type`` member is auto-retargeted to ``type``).

Revision ID: 0038_conversation_cols
Revises: 0037_conversations_rename
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0038_conversation_cols"
down_revision: Union[str, None] = "0037_conversations_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    insp = inspect(bind)
    conv = _cols(insp, "conversations")
    msg = _cols(insp, "conversation_messages")

    # ── conversations ────────────────────────────────────────────────
    if "session_type" in conv and "type" not in conv:
        op.alter_column("conversations", "session_type", new_column_name="type")
        if not is_sqlite:
            op.execute(
                "ALTER INDEX IF EXISTS ix_conversations_session_type "
                "RENAME TO ix_conversations_type"
            )
    if "interview_id" in conv:
        # drop_column cascades the single-column index + FK on Postgres.
        op.drop_column("conversations", "interview_id")
    if "mock_interview_state" in conv:
        op.drop_column("conversations", "mock_interview_state")

    # ── conversation_messages ────────────────────────────────────────
    if "session_id" in msg and "conversation_id" not in msg:
        op.alter_column(
            "conversation_messages", "session_id", new_column_name="conversation_id"
        )
        if not is_sqlite:
            op.execute(
                "ALTER INDEX IF EXISTS ix_conversation_messages_session_id "
                "RENAME TO ix_conversation_messages_conversation_id"
            )
            op.execute(
                "ALTER TABLE conversation_messages RENAME CONSTRAINT "
                "uq_conversation_messages_session_seq "
                "TO uq_conversation_messages_conversation_seq"
            )
    if "tool_call_id" not in msg:
        op.add_column(
            "conversation_messages",
            sa.Column("tool_call_id", sa.String(), nullable=True),
        )
    if "tool_name" not in msg:
        op.add_column(
            "conversation_messages",
            sa.Column("tool_name", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    insp = inspect(bind)
    conv = _cols(insp, "conversations")
    msg = _cols(insp, "conversation_messages")

    # ── conversation_messages ────────────────────────────────────────
    if "tool_name" in msg:
        op.drop_column("conversation_messages", "tool_name")
    if "tool_call_id" in msg:
        op.drop_column("conversation_messages", "tool_call_id")
    if "conversation_id" in msg and "session_id" not in msg:
        if not is_sqlite:
            op.execute(
                "ALTER TABLE conversation_messages RENAME CONSTRAINT "
                "uq_conversation_messages_conversation_seq "
                "TO uq_conversation_messages_session_seq"
            )
            op.execute(
                "ALTER INDEX IF EXISTS ix_conversation_messages_conversation_id "
                "RENAME TO ix_conversation_messages_session_id"
            )
        op.alter_column(
            "conversation_messages", "conversation_id", new_column_name="session_id"
        )

    # ── conversations ────────────────────────────────────────────────
    if "mock_interview_state" not in conv:
        op.add_column(
            "conversations", sa.Column("mock_interview_state", sa.Text(), nullable=True)
        )
    if "interview_id" not in conv:
        op.add_column(
            "conversations",
            sa.Column("interview_id", sa.String(), nullable=True),
        )
        if not is_sqlite:
            op.create_foreign_key(
                "conversations_interview_id_fkey",
                "conversations",
                "interview_records",
                ["interview_id"],
                ["id"],
            )
            op.create_index(
                "ix_conversations_interview_id", "conversations", ["interview_id"]
            )
    if "type" in conv and "session_type" not in conv:
        if not is_sqlite:
            op.execute(
                "ALTER INDEX IF EXISTS ix_conversations_type "
                "RENAME TO ix_conversations_session_type"
            )
        op.alter_column("conversations", "type", new_column_name="session_type")
