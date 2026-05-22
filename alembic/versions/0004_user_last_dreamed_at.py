"""Add users.last_dreamed_at for the autoDream cursor.

The Path B nightly dreaming worker (``app.services.memory.dreaming_worker``)
now uses a per-user cursor instead of per-record. The cursor's role is
analogous to Claude Code's ``.consolidate-lock`` file mtime — it gates
the next dream attempt for the user behind:

  * time:    NOW() - last_dreamed_at >= 24h
  * volume:  (new messages since last_dreamed_at >= 50)
             OR (new chat_sessions since last_dreamed_at > 3)

Without this column the gate would either always fire (no cursor) or
require an extra row in a dedicated cursor table — adding a nullable
column to users is cheaper and keeps the cursor co-located with the
user record it gates.

Revision ID: 0004_user_last_dreamed_at
Revises: 0003_drop_memory_items
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004_user_last_dreamed_at"
down_revision: Union[str, None] = "0003_drop_memory_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_dreamed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_dreamed_at")
