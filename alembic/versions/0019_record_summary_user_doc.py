"""add interview_records.debrief_summary + users.user_profile_doc

Backs two product changes:

  1. **debrief_summary** (per record) — populated at the end of the
     analysis pipeline with a 200-400 字 浓缩摘要. Injected into the
     ``record_context`` prompt slot for every debrief chat session
     under that record. Invariant within a record → caches cleanly.

  2. **user_profile_doc** (per user) — single markdown-ish text blob,
     one fact per line. Replaces the multi-row ``user_profile`` rows in
     ``memory_items`` (rule-based normalized_key dedup couldn't catch
     "User's name" vs "用户名" duplicates). Future extraction passes
     load this whole blob, hand it to the LLM along with the new
     conversation, and apply a returned patch list — never a full
     rewrite, so unrelated lines stay byte-stable.

We also DELETE the legacy ``memory_items WHERE type='user_profile'``
rows here — they're about to be re-derived from scratch into the new
doc on the next conversation, so keeping them around just creates
two competing sources of truth.

Revision ID: 0019_rec_sum_doc
Revises: 0018_drop_convs
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0019_rec_sum_doc"
down_revision: Union[str, None] = "0018_drop_convs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    if not _has_column("interview_records", "debrief_summary"):
        op.add_column(
            "interview_records",
            sa.Column("debrief_summary", sa.Text(), nullable=True),
        )
    if not _has_column("users", "user_profile_doc"):
        op.add_column(
            "users",
            sa.Column(
                "user_profile_doc",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
        )
    # Wipe legacy user_profile memory rows; the new doc is the source of
    # truth from here on. interview_fact rows are untouched.
    op.execute("DELETE FROM memory_items WHERE type = 'user_profile'")


def downgrade() -> None:
    if _has_column("users", "user_profile_doc"):
        op.drop_column("users", "user_profile_doc")
    if _has_column("interview_records", "debrief_summary"):
        op.drop_column("interview_records", "debrief_summary")
