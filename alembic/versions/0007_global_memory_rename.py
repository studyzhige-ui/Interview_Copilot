"""Rename memory_recall_default → global_memory_enabled.

Stage-H clarifies the toggle's semantics: it's the **global / cross-
session memory switch**, NOT a per-turn privacy gate. Session-local
context (recent_turns, session_state, [Record Context] for debrief
mode) is ALWAYS injected; only the v3 memory bundle
(user_profile + knowledge / strategy / habit docs) is gated by this
flag — same shape Claude Code's ``isAutoMemoryEnabled`` has.

The old name (``memory_recall_default``) was ambiguous about scope.
Renaming so the API surface + DB column + session_state JSON key all
say the same thing: ``global_memory_enabled``.

Single ``ALTER TABLE RENAME COLUMN`` is safe on Postgres + SQLite (via
batch_alter). No data loss — the column's boolean values are
preserved verbatim. session_state JSON keys are renamed at READ time
by ``recall_policy`` (back-compat shim for any old rows still using
``memory_recall_enabled``).

Revision ID: 0007_global_memory_rename
Revises: 0006_chat_message_content_blocks
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# Kept short — Postgres ``alembic_version.version_num`` is varchar(32).
revision: str = "0007_global_memory_rename"
down_revision: Union[str, None] = "0006_chat_message_content_blocks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite's stock ALTER TABLE doesn't support column rename in some
    # versions — batch_alter_table generates the copy-via-temp-table
    # workaround there and a plain ALTER TABLE on Postgres.
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "memory_recall_default",
            new_column_name="global_memory_enabled",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            existing_server_default=sa.text("false"),
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "global_memory_enabled",
            new_column_name="memory_recall_default",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            existing_server_default=sa.text("false"),
        )
