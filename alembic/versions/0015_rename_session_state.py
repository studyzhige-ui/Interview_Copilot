"""Rename ``chat_sessions.session_state`` → ``mock_interview_state``.

Pre-fix: the ``session_state`` JSON blob historically carried a grab-bag —
conversation mode, compaction summary, the memory toggle, AND mock-interview
runtime state. Those have since moved to dedicated columns: ``session_type``
(mode), ``summary`` (compaction summary), ``global_memory_enabled`` (toggle,
0014). The query planner also stopped reading the blob. What's left is purely
mock-interview runtime state, so the column is renamed to say so.

General / debrief sessions leave the column NULL. Existing non-mock rows keep
whatever vestigial JSON they had under the new name — harmless, nothing reads
it for those types.

Revision ID: 0015_rename_session_state
Revises: 0014_session_global_memory_col
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "0015_rename_session_state"
down_revision: Union[str, None] = "0014_session_global_memory_col"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: dev DBs that ran ``Base.metadata.create_all()`` after the
    # model rename already have ``mock_interview_state`` (and no ``session_state``).
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("chat_sessions")}
    if "session_state" in cols and "mock_interview_state" not in cols:
        op.alter_column(
            "chat_sessions",
            "session_state",
            new_column_name="mock_interview_state",
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("chat_sessions")}
    if "mock_interview_state" in cols and "session_state" not in cols:
        op.alter_column(
            "chat_sessions",
            "mock_interview_state",
            new_column_name="session_state",
        )
