"""Bounded, generation-fenced same-Turn recovery without changing user facts.

Revision ID: 0050
Revises: 0049
"""

from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversation_turns",
        sa.Column("dispatch_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column(
            "recovery_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.execute(
        "UPDATE conversation_turns SET dispatch_requested_at = COALESCE(heartbeat_at, started_at, created_at)"
    )


def downgrade():
    op.drop_column("conversation_turns", "recovery_attempts")
    op.drop_column("conversation_turns", "dispatch_requested_at")
