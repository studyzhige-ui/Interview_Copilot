"""Fence expired mock answer owners without changing historical transcripts.

Revision ID: 0051
Revises: 0050
"""

from alembic import op
import sqlalchemy as sa

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mock_interview_runtime",
        sa.Column(
            "answer_claim_generation", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade():
    op.drop_column("mock_interview_runtime", "answer_claim_generation")
