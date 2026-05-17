"""add users.memory_recall_default for the per-user opt-in toggle

A user-level preference that controls the DEFAULT memory-recall behaviour
across all sessions where the user hasn't explicitly toggled the session-
local switch. Memory recall is **opt-in**: a freshly registered account
will not have its past chat memories surfaced into the LLM prompt until
they enable it in 个人中心 (or flip the per-session toggle next to the
"agent" button).

Why a real column instead of a JSON ``preferences`` blob:
  * we only have one preference today; a single bool is much cheaper to
    read in the hot QA path than parsing JSON + jsonb_extract;
  * keeps the schema honest — future prefs can join in additive columns
    or graduate to a ``user_preferences`` table once we have 3+;
  * a default ``FALSE`` server-side means existing rows immediately match
    the new opt-in policy without a custom backfill loop.

Per-session override lives in ``chat_sessions.session_state`` JSON
(key ``memory_recall_enabled``), which is also nullable / opt-in. The
service-layer rule is: session_state value if present, else
``users.memory_recall_default``, else False.

Revision ID: 0016_user_mem_recall
Revises: 0015_chat_conv_id
Create Date: 2026-05-17

(revision id kept ≤ 32 chars; alembic_version is VARCHAR(32).)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0016_user_mem_recall"
down_revision: Union[str, None] = "0015_chat_conv_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    try:
        return any(c["name"] == column for c in inspector.get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    if not _has_column("users", "memory_recall_default"):
        op.add_column(
            "users",
            sa.Column(
                "memory_recall_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    if _has_column("users", "memory_recall_default"):
        op.drop_column("users", "memory_recall_default")
