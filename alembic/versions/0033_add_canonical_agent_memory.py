"""Add canonical user-level Long-term Agent Memory.

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("memory_recall_override", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("memory_contribution_override", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "memory_control_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_conversations_memory_control_version",
        "conversations",
        "memory_control_version >= 0",
    )

    op.create_table(
        "agent_memory_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("recall_enabled", sa.Boolean(), nullable=False),
        sa.Column("contribution_enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_agent_memory_settings_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_agent_memory_settings_user"),
    )
    op.create_index(
        "ix_agent_memory_settings_user_id",
        "agent_memory_settings",
        ["user_id"],
    )

    op.create_table(
        "long_term_agent_memories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("semantic_key", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("applicability", sa.Text(), nullable=False),
        sa.Column("tags_json", _jsonb(), nullable=False),
        sa.Column("valence", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("formed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_recalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recall_count", sa.Integer(), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','invalidated','deleted')",
            name="ck_long_term_agent_memories_status",
        ),
        sa.CheckConstraint(
            "valence IN ('effective','ineffective','mixed')",
            name="ck_long_term_agent_memories_valence",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_long_term_agent_memories_confidence",
        ),
        sa.CheckConstraint("version >= 1", name="ck_long_term_agent_memories_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "semantic_key",
            name="uq_long_term_agent_memories_user_semantic_key",
        ),
    )
    op.create_index(
        "ix_long_term_agent_memories_user_id",
        "long_term_agent_memories",
        ["user_id"],
    )
    op.create_index(
        "ix_long_term_agent_memories_user_status_updated",
        "long_term_agent_memories",
        ["user_id", "status", "updated_at"],
    )

    op.create_table(
        "long_term_agent_memory_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=True),
        sa.Column("source_turn_identity", sa.String(length=36), nullable=False),
        sa.Column("source_conversation_identity", sa.String(), nullable=False),
        sa.Column("support_quote_hash", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["long_term_agent_memories.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["conversation_turns.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "memory_id",
            "source_turn_identity",
            name="uq_long_term_agent_memory_sources_memory_turn",
        ),
    )
    op.create_index(
        "ix_long_term_agent_memory_sources_memory_id",
        "long_term_agent_memory_sources",
        ["memory_id"],
    )
    op.create_index(
        "ix_long_term_agent_memory_sources_turn_id",
        "long_term_agent_memory_sources",
        ["turn_id"],
    )
    op.create_index(
        "ix_long_term_agent_memory_sources_turn_identity",
        "long_term_agent_memory_sources",
        ["source_turn_identity"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_long_term_agent_memory_sources_turn_identity",
        table_name="long_term_agent_memory_sources",
    )
    op.drop_index(
        "ix_long_term_agent_memory_sources_turn_id",
        table_name="long_term_agent_memory_sources",
    )
    op.drop_index(
        "ix_long_term_agent_memory_sources_memory_id",
        table_name="long_term_agent_memory_sources",
    )
    op.drop_table("long_term_agent_memory_sources")
    op.drop_index(
        "ix_long_term_agent_memories_user_status_updated",
        table_name="long_term_agent_memories",
    )
    op.drop_index(
        "ix_long_term_agent_memories_user_id",
        table_name="long_term_agent_memories",
    )
    op.drop_table("long_term_agent_memories")
    op.drop_index(
        "ix_agent_memory_settings_user_id", table_name="agent_memory_settings"
    )
    op.drop_table("agent_memory_settings")
    op.drop_constraint(
        "ck_conversations_memory_control_version",
        "conversations",
        type_="check",
    )
    op.drop_column("conversations", "memory_control_version")
    op.drop_column("conversations", "memory_contribution_override")
    op.drop_column("conversations", "memory_recall_override")
