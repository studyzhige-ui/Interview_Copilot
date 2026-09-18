"""Persistent model replacement histories, separate from raw transcripts.

Revision ID: 0045
Revises: 0044
"""

from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "context_checkpoints",
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("scope", sa.String(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("through_seq", sa.Integer(), nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), nullable=False),
        sa.Column("window_id", sa.String(36), nullable=False),
        sa.Column("previous_window_id", sa.String(36)),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("context_checkpoints")
