"""Add user-managed Skill and MCP server configuration.

Revision ID: 0044_user_capabilities
Revises: 0043_interview_qa_answer_audio
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0044_user_capabilities"
down_revision: Union[str, None] = "0043_interview_qa_answer_audio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_skills",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_skills_user_name"),
    )
    op.create_index("ix_user_skills_user_id", "user_skills", ["user_id"])

    op.create_table(
        "user_mcp_servers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("transport", sa.String(length=24), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("args_json", sa.JSON(), nullable=False),
        sa.Column("secrets_ciphertext", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_status", sa.String(length=24), nullable=False, server_default="unchecked"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("tool_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_mcp_servers_user_name"),
    )
    op.create_index("ix_user_mcp_servers_user_id", "user_mcp_servers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_mcp_servers_user_id", table_name="user_mcp_servers")
    op.drop_table("user_mcp_servers")
    op.drop_index("ix_user_skills_user_id", table_name="user_skills")
    op.drop_table("user_skills")
