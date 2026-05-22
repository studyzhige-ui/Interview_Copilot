"""Add one_liner to strategy_docs and habit_docs.

Phase A redesign: strategy_doc and habit_doc are no longer auto-loaded
into every chat turn's prompt. Instead the universal context layer
exposes only a one-line description per doc, and the selection LLM
decides whether to pull the full body for the current query. This
mirrors knowledge_doc's index-then-body pattern.

``one_liner`` defaults to empty string. The doc service maintains it
on every successful write (derived from the body when the LLM didn't
provide one explicitly). Backfilling existing rows is unnecessary —
empty one_liner just shows the doc as "(no description)" in the
universal pass until the next dream/realtime write fills it.

Revision ID: 0005_single_doc_one_liner
Revises: 0004_user_last_dreamed_at
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005_single_doc_one_liner"
down_revision: Union[str, None] = "0004_user_last_dreamed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "strategy_docs",
        sa.Column("one_liner", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "habit_docs",
        sa.Column("one_liner", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("habit_docs", "one_liner")
    op.drop_column("strategy_docs", "one_liner")
