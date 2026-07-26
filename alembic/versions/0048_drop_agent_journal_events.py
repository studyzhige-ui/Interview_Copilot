"""Remove the superseded tool journal table.

Revision ID: 0048_drop_agent_journal_events
Revises: 0047_capability_runtime_layers
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0048_drop_agent_journal_events"
down_revision: Union[str, None] = "0047_capability_runtime_layers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_agent_journal_events_session_id", table_name="agent_journal_events")
    op.drop_table("agent_journal_events")


def downgrade() -> None:
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
    op.create_index(
        "ix_agent_journal_events_session_id",
        "agent_journal_events",
        ["session_id"],
    )
