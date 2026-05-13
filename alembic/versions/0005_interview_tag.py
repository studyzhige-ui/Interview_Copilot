"""add tag column to interview_records

Revision ID: 0005_interview_tag
Revises: 0004_user_profile
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_interview_tag"
down_revision: Union[str, None] = "0004_user_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interview_records", sa.Column("tag", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_records", "tag")
