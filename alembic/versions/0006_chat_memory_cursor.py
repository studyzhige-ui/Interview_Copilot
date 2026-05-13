"""add chat_sessions.memory_extraction_cursor

The ChatSession model declared `memory_extraction_cursor` but it was never
created in alembic — the table was carried over from an early migration
without this column. Code in chat_history_service / post_turn_maintenance
reads and writes it, so any chat-session INSERT or SELECT crashes with
``UndefinedColumn``. This migration backfills the missing column.

Revision ID: 0006_chat_memory_cursor
Revises: 0005_interview_tag
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_chat_memory_cursor"
down_revision: Union[str, None] = "0005_interview_tag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column(
            "memory_extraction_cursor",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_sessions", "memory_extraction_cursor")
