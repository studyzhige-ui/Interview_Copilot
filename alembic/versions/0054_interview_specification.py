"""Freeze practice purpose on the durable interview, independent of transport.

Revision ID: 0054
Revises: 0053
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "interview_records",
        sa.Column(
            "specification_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    # Old rows are not rewritten: NULL is the explicit historic full-interview
    # contract. Current writes freeze the validated specification at creation.


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM interview_records WHERE specification_json IS NOT NULL"
        )
    ):
        raise RuntimeError("interview_specification_requires_export_before_rollback")
    op.drop_column("interview_records", "specification_json")
