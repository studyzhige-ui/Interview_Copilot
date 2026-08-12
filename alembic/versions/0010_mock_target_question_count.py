"""Add the advisory target length for live mock interviews.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mock_interview_runtime",
        sa.Column(
            "target_question_count",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
    )
    op.alter_column(
        "mock_interview_runtime",
        "target_question_count",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("mock_interview_runtime", "target_question_count")
