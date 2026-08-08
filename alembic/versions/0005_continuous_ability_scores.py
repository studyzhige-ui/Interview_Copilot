"""Preserve decimal interview evidence and add continuous ability scores.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "interview_qa",
        "score",
        existing_type=sa.Integer(),
        type_=sa.Float(),
        existing_nullable=True,
    )
    op.add_column(
        "memory_ability_states",
        sa.Column("ability_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "memory_ability_states",
        sa.Column("score_version", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memory_ability_states", "score_version")
    op.drop_column("memory_ability_states", "ability_score")
    op.alter_column(
        "interview_qa",
        "score",
        existing_type=sa.Float(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="round(score)::integer",
    )
