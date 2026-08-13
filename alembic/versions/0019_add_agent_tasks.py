"""Add the single optional flat AgentTask owned by a Turn.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("completion_conditions_json", _jsonb(), nullable=False),
        sa.Column("phases_json", _jsonb(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("creation_idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("creation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version >= 1", name="ck_agent_tasks_version_positive"),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id", name="uq_agent_tasks_turn"),
    )
    op.create_index("ix_agent_tasks_turn_id", "agent_tasks", ["turn_id"])
    op.create_table(
        "agent_task_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_task_id", sa.String(length=35), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("from_version", sa.Integer(), nullable=False),
        sa.Column("to_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_phase_ids_json", _jsonb(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "from_version >= 1 AND to_version = from_version + 1",
            name="ck_agent_task_revisions_version_step",
        ),
        sa.ForeignKeyConstraint(
            ["agent_task_id"], ["agent_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_task_id",
            "idempotency_key",
            name="uq_agent_task_revisions_idempotency",
        ),
        sa.UniqueConstraint(
            "agent_task_id",
            "to_version",
            name="uq_agent_task_revisions_to_version",
        ),
    )
    op.create_index(
        "ix_agent_task_revisions_agent_task_id",
        "agent_task_revisions",
        ["agent_task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_task_revisions_agent_task_id",
        table_name="agent_task_revisions",
    )
    op.drop_table("agent_task_revisions")
    op.drop_index("ix_agent_tasks_turn_id", table_name="agent_tasks")
    op.drop_table("agent_tasks")
