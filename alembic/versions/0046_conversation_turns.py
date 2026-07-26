"""Decouple conversation turns from SSE connections.

Revision ID: 0046_conversation_turns
Revises: 0045_agent_task_recovery
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0046_conversation_turns"
down_revision: Union[str, None] = "0045_agent_task_recovery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("active_turn_id", sa.String(), nullable=True))
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("user_message_seq", sa.Integer(), nullable=True),
        sa.Column("assistant_message_seq", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_turns_conversation_id", "conversation_turns", ["conversation_id"])
    op.create_index("ix_conversation_turns_user_id", "conversation_turns", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_turns_user_id", table_name="conversation_turns")
    op.drop_index("ix_conversation_turns_conversation_id", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_column("conversations", "active_turn_id")
