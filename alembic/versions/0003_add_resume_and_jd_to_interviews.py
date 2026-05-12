"""add resume and JD context columns to interviews table

Revision ID: 0003_add_resume_and_jd_to_interviews
Revises: 0002_context_memory_refactor
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_add_resume_and_jd_to_interviews"
down_revision: Union[str, None] = "0002_context_memory_refactor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interviews",
        sa.Column("resume_upload_id", sa.String(), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("jd_text", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_interviews_resume_upload_id", "interviews", ["resume_upload_id"]
    )
    op.create_foreign_key(
        "fk_interviews_resume_upload_id",
        "interviews",
        "user_uploads",
        ["resume_upload_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_interviews_resume_upload_id", "interviews", type_="foreignkey")
    op.drop_index("ix_interviews_resume_upload_id", "interviews")
    op.drop_column("interviews", "jd_text")
    op.drop_column("interviews", "resume_upload_id")
