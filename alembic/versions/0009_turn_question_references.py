"""Persist explicit debrief-question references on durable chat turns.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_turns",
        sa.Column(
            "question_indexes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column(
        "conversation_turns",
        "question_indexes_json",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("conversation_turns", "question_indexes_json")
