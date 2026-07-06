"""Add ``interview_qa.answer_audio_file_asset_id`` (MOCK-7).

Mock voice answers keep their original clip: the review pipeline copies the
clip's file_assets.id from the conversation message's audio content block
onto the frozen QA row, and the API mints a fresh presigned GET into the
(previously dead) ``answer_audio_url`` field at read time.

Revision ID: 0043_interview_qa_answer_audio
Revises: 0042_session_tasks
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0043_interview_qa_answer_audio"
down_revision: Union[str, None] = "0042_session_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("interview_qa")}
    if "answer_audio_file_asset_id" in cols:
        return
    op.add_column(
        "interview_qa",
        sa.Column("answer_audio_file_asset_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interview_qa", "answer_audio_file_asset_id")
