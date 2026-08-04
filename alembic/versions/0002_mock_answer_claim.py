"""Add the mock-interview answer submission lease.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mock_interview_runtime",
        sa.Column("answer_claimed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mock_interview_runtime", "answer_claimed_at")
