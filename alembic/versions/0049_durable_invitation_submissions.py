"""Durable exact UI commands and cancellation tombstones.

Revision ID: 0049
Revises: 0048
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "invitation_submissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_fingerprint", sa.String(64), nullable=True),
        sa.Column("request_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "operation_id",
            sa.String(36),
            sa.ForeignKey("application_operations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rejection_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','committed','rejected','cancelled')",
            name="ck_invitation_submissions_status",
        ),
    )
    op.create_index(
        "ix_invitation_submissions_owner_status",
        "invitation_submissions",
        ["user_id", "status"],
    )


def downgrade():
    op.drop_table("invitation_submissions")
