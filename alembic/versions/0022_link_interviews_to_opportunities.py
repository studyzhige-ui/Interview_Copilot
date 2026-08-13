"""Link an InterviewRecord to an optional owned JobOpportunity.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interview_records",
        sa.Column("job_opportunity_id", sa.String(length=35), nullable=True),
    )
    op.create_foreign_key(
        "fk_interview_records_job_opportunity_id_job_opportunities",
        "interview_records",
        "job_opportunities",
        ["job_opportunity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_interview_records_job_opportunity_id",
        "interview_records",
        ["job_opportunity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_records_job_opportunity_id",
        table_name="interview_records",
    )
    op.drop_constraint(
        "fk_interview_records_job_opportunity_id_job_opportunities",
        "interview_records",
        type_="foreignkey",
    )
    op.drop_column("interview_records", "job_opportunity_id")
