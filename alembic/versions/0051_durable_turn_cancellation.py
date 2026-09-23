"""Persist cancellation independently of the event transport."""

from alembic import op
import sqlalchemy as sa

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversation_turns",
        sa.Column(
            "cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    op.drop_column("conversation_turns", "cancel_requested")
