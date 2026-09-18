"""Bind durable tool identities to exact inputs, separate from redacted audit.

Revision ID: 0046
Revises: 0045
"""

from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agent_tool_calls", sa.Column("arguments_digest", sa.String(64), nullable=True)
    )


def downgrade():
    op.drop_column("agent_tool_calls", "arguments_digest")
