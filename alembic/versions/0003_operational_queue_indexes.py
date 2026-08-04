"""Align hot indexes with resource-isolated queue and resume queries.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_outbox_jobs_status_next_run", table_name="outbox_jobs")
    op.create_index(
        "ix_outbox_jobs_type_status_next_run",
        "outbox_jobs",
        ["job_type", "status", "next_run_at"],
        unique=False,
    )
    op.drop_index("ix_mock_runtime_user_status", table_name="mock_interview_runtime")
    op.create_index(
        "ix_mock_runtime_user_status_activity",
        "mock_interview_runtime",
        ["user_id", "status", "last_activity_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mock_runtime_user_status_activity",
        table_name="mock_interview_runtime",
    )
    op.create_index(
        "ix_mock_runtime_user_status",
        "mock_interview_runtime",
        ["user_id", "status"],
        unique=False,
    )
    op.drop_index(
        "ix_outbox_jobs_type_status_next_run",
        table_name="outbox_jobs",
    )
    op.create_index(
        "ix_outbox_jobs_status_next_run",
        "outbox_jobs",
        ["status", "next_run_at"],
        unique=False,
    )
