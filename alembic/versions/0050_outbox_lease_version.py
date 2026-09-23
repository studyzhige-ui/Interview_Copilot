"""Fence outbox attempts independently of worker host identity."""

from alembic import op
import sqlalchemy as sa

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "outbox_jobs",
        sa.Column("lease_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("outbox_jobs", "lease_version")
