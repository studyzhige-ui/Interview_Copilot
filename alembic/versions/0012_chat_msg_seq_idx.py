"""chat_messages: composite (session_id, seq) index for fast history pagination

Every chat-history fetch filters ``session_id = ?`` and orders by ``seq``.
The existing per-column indexes can't satisfy that as a single index scan,
so once a session accumulates ~1k+ messages the planner falls back to a
seq scan + sort. A composite index turns that into a single B-tree range.

Revision ID: 0012_chat_msg_seq_idx
Revises: 0011_qa_director_fields
Create Date: 2026-05-14

(revision id kept ≤ 32 chars; alembic_version is VARCHAR(32).)
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012_chat_msg_seq_idx"
down_revision: Union[str, None] = "0011_qa_director_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_chat_messages_session_seq",
        "chat_messages",
        ["session_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_seq", table_name="chat_messages")
