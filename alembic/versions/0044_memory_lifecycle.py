"""Durable two-phase memory lifecycle and read receipts.

Revision ID: 0044
Revises: 0043
"""

from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "long_term_agent_memories",
        sa.Column("origin", sa.String(16), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "long_term_agent_memories",
        sa.Column("index_text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "long_term_agent_memories",
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "long_term_agent_memories",
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "long_term_agent_memories",
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "memory_extractions",
        sa.Column("turn_id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("candidates_json", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("user_id", "conversation_id", "status"):
        op.create_index(f"ix_memory_extractions_{name}", "memory_extractions", [name])
    op.create_table(
        "memory_workspaces",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("index_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "memory_read_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "turn_id",
            sa.String(),
            sa.ForeignKey("conversation_turns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "memory_id",
            sa.String(36),
            sa.ForeignKey("long_term_agent_memories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("memory_version", sa.Integer(), nullable=False),
        sa.Column("cited_at", sa.DateTime(timezone=True)),
        sa.Column("feedback", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("user_id", "turn_id", "memory_id"):
        op.create_index(
            f"ix_memory_read_receipts_{name}", "memory_read_receipts", [name]
        )


def downgrade():
    op.drop_table("memory_read_receipts")
    op.drop_table("memory_workspaces")
    op.drop_table("memory_extractions")
    for name in (
        "usage_count",
        "last_used_at",
        "evidence_json",
        "index_text",
        "origin",
    ):
        op.drop_column("long_term_agent_memories", name)
