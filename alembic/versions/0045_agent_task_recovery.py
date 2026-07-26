"""Add task verification fields and durable Agent recovery state.

Revision ID: 0045_agent_task_recovery
Revises: 0044_user_capabilities
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0045_agent_task_recovery"
down_revision: Union[str, None] = "0044_user_capabilities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_tasks", sa.Column("parent_task_id", sa.Integer(), nullable=True))
    op.add_column("session_tasks", sa.Column("owner", sa.String(length=64), nullable=True))
    op.add_column("session_tasks", sa.Column("blocked_by_json", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("session_tasks", sa.Column("acceptance_criteria", sa.Text(), nullable=False, server_default=""))
    op.add_column("session_tasks", sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("session_tasks", sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="unverified"))
    op.add_column("session_tasks", sa.Column("verification_notes", sa.Text(), nullable=True))
    op.add_column("session_tasks", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "agent_journal_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "event_key", name="uq_agent_journal_session_event"),
    )
    op.create_index("ix_agent_journal_events_session_id", "agent_journal_events", ["session_id"])

    op.create_table(
        "agent_checkpoints",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("current_task_id", sa.Integer(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("agent_checkpoints")
    op.drop_index("ix_agent_journal_events_session_id", table_name="agent_journal_events")
    op.drop_table("agent_journal_events")
    for column in (
        "attempt_count",
        "verification_notes",
        "verification_status",
        "evidence_json",
        "acceptance_criteria",
        "blocked_by_json",
        "owner",
        "parent_task_id",
    ):
        op.drop_column("session_tasks", column)
