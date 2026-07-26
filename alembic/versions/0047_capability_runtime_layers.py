"""Persist session, turn, and tool-call capability state.

Revision ID: 0047_capability_runtime_layers
Revises: 0046_conversation_turns
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0047_capability_runtime_layers"
down_revision: Union[str, None] = "0046_conversation_turns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_capability_states",
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("discovered_skills_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("permissions_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("tool_history_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "ix_conversation_capability_states_user_id",
        "conversation_capability_states",
        ["user_id"],
    )

    op.add_column(
        "conversation_turns",
        sa.Column("capability_snapshot_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("loaded_schemas_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("budget_json", sa.JSON(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id", "call_id", name="uq_agent_tool_calls_turn_call"),
    )
    op.create_index("ix_agent_tool_calls_turn_id", "agent_tool_calls", ["turn_id"])
    op.create_index("ix_agent_tool_calls_session_id", "agent_tool_calls", ["session_id"])
    op.create_index("ix_agent_tool_calls_user_id", "agent_tool_calls", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_tool_calls_user_id", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_session_id", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_turn_id", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_column("conversation_turns", "budget_json")
    op.drop_column("conversation_turns", "loaded_schemas_json")
    op.drop_column("conversation_turns", "capability_snapshot_json")
    op.drop_index(
        "ix_conversation_capability_states_user_id",
        table_name="conversation_capability_states",
    )
    op.drop_table("conversation_capability_states")
