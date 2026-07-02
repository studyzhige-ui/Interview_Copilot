"""Add ``session_tasks`` table for agent task tracking.

V2 task system: session-scoped tasks that persist across turns so the agent
can track multi-step work.  Claude Code V2 alignment (TaskCreate/Update/Get/List).

Revision ID: 0042_session_tasks
Revises: 0041_document_chunk_provenance
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0042_session_tasks"
down_revision: Union[str, None] = "0041_document_chunk_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "session_tasks" in inspector.get_table_names():
        return
    op.create_table(
        "session_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "task_id", name="uq_session_tasks_session_task"),
    )
    op.create_index(
        "ix_session_tasks_session_status",
        "session_tasks",
        ["session_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "session_tasks" in inspect(bind).get_table_names():
        op.drop_table("session_tasks")
