"""CONVERSATION-MOCK (part A): rename chat_sessions->conversations and
chat_messages->conversation_messages (table + indexes/constraint only).

Pure rename — columns are unchanged in this step (column renames
session_type->type / session_id->conversation_id, the interview_id /
mock_interview_state drops, and the mock-runtime rewrite are part B). On
Postgres ``rename_table`` auto-updates dependent FK references; indexes + the
unique constraint are renamed explicitly to match the new table names.

Revision ID: 0037_conversations_rename
Revises: 0036_credential_validation
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "0037_conversations_rename"
down_revision: Union[str, None] = "0036_credential_validation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old_index_name, new_index_name)
_CONV_IDX = [
    ("ix_chat_sessions_user_type_arch", "ix_conversations_user_type_arch"),
    ("ix_chat_sessions_user_updated", "ix_conversations_user_updated"),
    ("ix_chat_sessions_id", "ix_conversations_id"),
    ("ix_chat_sessions_user_id", "ix_conversations_user_id"),
    ("ix_chat_sessions_session_type", "ix_conversations_session_type"),
    ("ix_chat_sessions_interview_id", "ix_conversations_interview_id"),
]
_MSG_IDX = [
    ("ix_chat_messages_id", "ix_conversation_messages_id"),
    ("ix_chat_messages_session_id", "ix_conversation_messages_session_id"),
    ("ix_chat_messages_seq", "ix_conversation_messages_seq"),
]


def _tables(insp) -> set[str]:
    return set(insp.get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    tables = _tables(inspect(bind))

    if "chat_sessions" in tables and "conversations" not in tables:
        op.rename_table("chat_sessions", "conversations")
    if "chat_messages" in tables and "conversation_messages" not in tables:
        op.rename_table("chat_messages", "conversation_messages")

    if not is_sqlite:
        for old, new in _CONV_IDX + _MSG_IDX:
            op.execute(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")
        op.execute(
            "ALTER TABLE conversation_messages RENAME CONSTRAINT "
            "uq_chat_messages_session_seq TO uq_conversation_messages_session_seq"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    tables = _tables(inspect(bind))

    if not is_sqlite:
        op.execute(
            "ALTER TABLE conversation_messages RENAME CONSTRAINT "
            "uq_conversation_messages_session_seq TO uq_chat_messages_session_seq"
        )
        for old, new in _CONV_IDX + _MSG_IDX:
            op.execute(f"ALTER INDEX IF EXISTS {new} RENAME TO {old}")

    if "conversation_messages" in tables and "chat_messages" not in tables:
        op.rename_table("conversation_messages", "chat_messages")
    if "conversations" in tables and "chat_sessions" not in tables:
        op.rename_table("conversations", "chat_sessions")
