"""Add ordering and lifecycle facts to canonical Agent Tool Calls.

Revision ID: 0037
Revises: 0036
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_tool_calls", sa.Column("model_step", sa.Integer()))
    op.add_column("agent_tool_calls", sa.Column("model_call_index", sa.Integer()))
    op.add_column("agent_tool_calls", sa.Column("model_call_order", sa.Integer()))
    op.add_column("agent_tool_calls", sa.Column("completion_sequence", sa.Integer()))
    op.add_column(
        "agent_tool_calls", sa.Column("handler_identity", sa.String(length=255))
    )
    op.add_column(
        "agent_tool_calls", sa.Column("provider_identity", sa.String(length=255))
    )
    op.add_column(
        "agent_tool_calls", sa.Column("connection_identity", sa.String(length=255))
    )
    op.add_column(
        "agent_tool_calls",
        sa.Column(
            "timeline_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "agent_tool_calls",
        sa.Column(
            "receipt_refs_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_tool_calls_turn_model_order",
        "agent_tool_calls",
        ["turn_id", "model_call_order"],
        unique=False,
    )
    op.create_index(
        "ix_agent_tool_calls_turn_completion",
        "agent_tool_calls",
        ["turn_id", "completion_sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tool_calls_turn_completion", table_name="agent_tool_calls")
    op.drop_index("ix_agent_tool_calls_turn_model_order", table_name="agent_tool_calls")
    op.drop_column("agent_tool_calls", "receipt_refs_json")
    op.drop_column("agent_tool_calls", "timeline_json")
    op.drop_column("agent_tool_calls", "connection_identity")
    op.drop_column("agent_tool_calls", "provider_identity")
    op.drop_column("agent_tool_calls", "handler_identity")
    op.drop_column("agent_tool_calls", "completion_sequence")
    op.drop_column("agent_tool_calls", "model_call_order")
    op.drop_column("agent_tool_calls", "model_call_index")
    op.drop_column("agent_tool_calls", "model_step")
