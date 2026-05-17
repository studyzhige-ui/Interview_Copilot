"""add conversation_id to chat_messages + current_conversation_id to chat_sessions

Splits a ``chat_session`` into multiple isolated conversations. Before this
migration, every message in a session was part of one long thread; if a user
wanted to start a fresh chat in the same debrief panel they had to create a
new session, which polluted the session list. Now a session can host N
conversations, switched via a "新对话" button in the UI.

Design:
  * ``chat_messages.conversation_id`` — nullable ``String``. Every message
    belongs to exactly one conversation. Old rows are backfilled with the
    parent session's id (so legacy sessions appear as "one conversation
    whose id equals the session id" — 1:1 backward-compat, no orphaned
    messages).
  * ``chat_sessions.current_conversation_id`` — nullable ``String``.
    Points to the active conversation a new turn should land in.
    Backfilled to ``id`` (matches the message backfill above). The
    "新对话" button generates a fresh UUID and updates this pointer;
    subsequent turns get the new conversation_id.
  * Index ``ix_chat_msgs_session_conv_seq`` on
    ``(session_id, conversation_id, seq)`` — covers transcript queries
    that filter by session+conversation and order by seq.

Why nullable: keeps backfill cheap (no NOT NULL alter) and lets older
clients that don't know about conversations still work — the service
layer treats NULL as "default conversation" and writes the session id.

Revision ID: 0015_chat_conv_id
Revises: 0014_hot_query_idxs
Create Date: 2026-05-17

(revision id kept ≤ 32 chars; alembic_version is VARCHAR(32).)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0015_chat_conv_id"
down_revision: Union[str, None] = "0014_hot_query_idxs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    try:
        return any(c["name"] == column for c in inspector.get_columns(table))
    except Exception:
        return False


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    try:
        return any(ix["name"] == name for ix in inspector.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    # ── chat_messages.conversation_id ────────────────────────────────────
    if not _has_column("chat_messages", "conversation_id"):
        op.add_column(
            "chat_messages",
            sa.Column("conversation_id", sa.String(), nullable=True),
        )
    # Backfill: existing messages inherit the parent session's id so
    # legacy sessions render as a single conversation seamlessly.
    op.execute(
        "UPDATE chat_messages "
        "SET conversation_id = session_id "
        "WHERE conversation_id IS NULL"
    )

    # ── chat_sessions.current_conversation_id ────────────────────────────
    if not _has_column("chat_sessions", "current_conversation_id"):
        op.add_column(
            "chat_sessions",
            sa.Column("current_conversation_id", sa.String(), nullable=True),
        )
    op.execute(
        "UPDATE chat_sessions "
        "SET current_conversation_id = id "
        "WHERE current_conversation_id IS NULL"
    )

    # ── Composite index for (session, conversation) transcript queries ──
    if not _has_index("chat_messages", "ix_chat_msgs_session_conv_seq"):
        op.create_index(
            "ix_chat_msgs_session_conv_seq",
            "chat_messages",
            ["session_id", "conversation_id", "seq"],
            unique=False,
        )


def downgrade() -> None:
    if _has_index("chat_messages", "ix_chat_msgs_session_conv_seq"):
        op.drop_index("ix_chat_msgs_session_conv_seq", table_name="chat_messages")
    if _has_column("chat_sessions", "current_conversation_id"):
        op.drop_column("chat_sessions", "current_conversation_id")
    if _has_column("chat_messages", "conversation_id"):
        op.drop_column("chat_messages", "conversation_id")
