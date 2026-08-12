"""Remove record-level artifacts with no product consumer.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("interview_records", "debrief_summary")
    op.drop_column("interview_records", "interview_plan")


def downgrade() -> None:
    op.add_column(
        "interview_records",
        sa.Column("interview_plan", sa.Text(), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("debrief_summary", sa.Text(), nullable=True),
    )
