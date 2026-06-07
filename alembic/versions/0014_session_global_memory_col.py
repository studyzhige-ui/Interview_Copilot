"""Add per-session ``global_memory_enabled`` column to ``chat_sessions``.

Pre-fix: the per-session memory toggle was stored as a JSON key
(``global_memory_enabled`` / legacy ``memory_recall_enabled``) inside the
``chat_sessions.session_state`` blob. That blob is being narrowed to hold
only mock-interview / conversation-mode state, so the toggle moves to its
own first-class nullable Boolean column.

Resolution: ``chat_sessions.global_memory_enabled`` (NULL = fall through to
the per-user ``users.global_memory_enabled`` default). ``recall_policy``
reads and writes THIS column now; the JSON read shim is gone.

In-flight sessions that carried a per-session override only in the JSON blob
fall back to the per-user default after this migration — acceptable for a
niche toggle, and no data migration is attempted (keeps the migration
backend-agnostic).

Revision ID: 0014_session_global_memory_col
Revises: 0013_user_provider_settings
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0014_session_global_memory_col"
down_revision: Union[str, None] = "0013_user_provider_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: dev DBs that ran ``Base.metadata.create_all()`` after the
    # ChatSession model gained the column will already have it.
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("chat_sessions")}
    if "global_memory_enabled" not in cols:
        op.add_column(
            "chat_sessions",
            sa.Column("global_memory_enabled", sa.Boolean(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("chat_sessions", "global_memory_enabled")
