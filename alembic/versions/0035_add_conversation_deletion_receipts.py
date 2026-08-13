"""Add bounded receipt tombstones for deleted Conversations.

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "conversation_deletion_receipts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("deleted_conversation_id", sa.String(length=128), nullable=False),
        sa.Column("turn_id", sa.String(length=128), nullable=False),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("effect", sa.String(length=32), nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("correlation_json", _jsonb(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deleted_conversation_id",
            "turn_id",
            "call_id",
            name="uq_conversation_deletion_receipt_call",
        ),
    )
    op.create_index(
        "ix_conversation_deletion_receipts_user_id",
        "conversation_deletion_receipts",
        ["user_id"],
    )
    op.create_index(
        "ix_conversation_deletion_receipts_deleted_conversation_id",
        "conversation_deletion_receipts",
        ["deleted_conversation_id"],
    )
    op.create_index(
        "ix_conversation_deletion_receipts_status",
        "conversation_deletion_receipts",
        ["status"],
    )
    op.create_index(
        "ix_conversation_deletion_receipts_retain_until",
        "conversation_deletion_receipts",
        ["retain_until"],
    )
    op.create_index(
        "ix_conversation_deletion_receipts_user_status",
        "conversation_deletion_receipts",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("conversation_deletion_receipts")
