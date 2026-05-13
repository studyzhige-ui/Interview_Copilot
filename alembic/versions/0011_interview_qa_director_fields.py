"""interview_qa: Runtime Director metadata fields

Adds three columns produced by the v6 Runtime Director per turn:
  - action: the director's decision label (follow_up / new_question / transition /
    hint / clarify / reverse_answer / finish) — useful for review-side filtering
  - topic: snake_case topic tag that downstream summarization + topic dedupe
    rely on; replaces the awkward "stuff a single topic into grounding_refs_json"
    pattern v5 used
  - answer_quality_json: { level, reason } captured live by the director so the
    finish-time analyzer can use it as a prior instead of re-judging from scratch

A regular index on topic for "find all QAs about X" queries.

Revision ID: 0011_interview_qa_director_fields
Revises: 0010_avatar_text
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_interview_qa_director_fields"
down_revision: Union[str, None] = "0010_avatar_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("interview_qa") as batch:
        batch.add_column(sa.Column("action", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("topic", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("answer_quality_json", sa.JSON(), nullable=True))
    op.create_index("ix_interview_qa_topic", "interview_qa", ["topic"])


def downgrade() -> None:
    op.drop_index("ix_interview_qa_topic", table_name="interview_qa")
    with op.batch_alter_table("interview_qa") as batch:
        batch.drop_column("answer_quality_json")
        batch.drop_column("topic")
        batch.drop_column("action")
