"""interview_records: composite (user_id, created_at desc) index for fast list pagination

The dashboard / review list query is ``WHERE user_id = ? ORDER BY created_at
DESC LIMIT N OFFSET M``. With only single-column indexes the planner has to
fetch all of one user's records and sort. Composite (user_id, created_at)
satisfies both filter and order in a single B-tree range scan.

Revision ID: 0013_iv_rec_user_ct_idx
Revises: 0012_chat_msg_seq_idx
Create Date: 2026-05-14

(revision id kept ≤ 32 chars; alembic_version is VARCHAR(32).)
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013_iv_rec_user_ct_idx"
down_revision: Union[str, None] = "0012_chat_msg_seq_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_interview_records_user_created",
        "interview_records",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_interview_records_user_created", table_name="interview_records")
