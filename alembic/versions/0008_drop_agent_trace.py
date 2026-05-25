"""Drop agent_runs + agent_steps tables.

The agent_trace_service that wrote these tables was redundant with
LangSmith's wrap_openai instrumentation: every LLM call (planner,
agent, summarizer, brief, compaction, mock director) is already
captured by LangSmith with full prompt + response + token usage +
latency + parent-child trace structure, and LangSmith ships a UI
for browsing.

The only thing agent_trace captured that LangSmith doesn't natively
expose was the parsed tool args + observation JSON for each step —
but those are visible inside LangSmith's per-call view of the
agent's LLM response (the tool_calls field of the assistant message).

User-facing surfaces (chat panel tool cards) get their data from
``chat_messages.content_blocks_json`` — which is the canonical
persisted tool-use / tool-result chain — not from agent_steps. So
dropping these tables affects exactly zero FE behavior.

Revision ID: 0008_drop_agent_trace
Revises: 0007_global_memory_rename
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_drop_agent_trace"
down_revision: Union[str, None] = "0007_global_memory_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop child table first (FK ordering).
    op.drop_index("ix_agent_steps_run_id", table_name="agent_steps")
    op.drop_index("ix_agent_steps_id", table_name="agent_steps")
    op.drop_table("agent_steps")

    op.drop_index("ix_agent_runs_session_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_id", table_name="agent_runs")
    op.drop_table("agent_runs")


def downgrade() -> None:
    # Recreate exactly as 0001_baseline did. If you actually want the
    # trace stack back, you also need to revive ``agent_trace_service.py``
    # and the orphan endpoints — the tables alone don't write themselves.
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), primary_key=True, index=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="function_calling"),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("final_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("budget_stop_reason", sa.String(), nullable=True),
        sa.Column("steps_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_latency_ms", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_agent_runs_id", "agent_runs", ["id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, index=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=True),
        sa.Column("tool_call_id", sa.String(), nullable=True),
        sa.Column("tool_args_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("observation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("assistant_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_error", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_steps_id", "agent_steps", ["id"])
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])
