"""Add the authoritative PersistentTask scheduler cursor.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "persistent_tasks",
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_persistent_tasks_schedule_due",
        "persistent_tasks",
        ["state", "trigger_kind", "next_due_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_persistent_tasks_schedule_due",
        table_name="persistent_tasks",
    )
    op.drop_column("persistent_tasks", "next_due_at")
