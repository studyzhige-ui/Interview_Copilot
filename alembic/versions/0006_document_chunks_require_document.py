"""Require every chunk to belong to a knowledge document.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM document_chunks WHERE document_id IS NULL")
    op.alter_column(
        "document_chunks",
        "document_id",
        existing_type=sa.String(),
        nullable=False,
    )
    op.drop_column("document_chunks", "lexical_index_id")


def downgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("lexical_index_id", sa.String(), nullable=True),
    )
    op.alter_column(
        "document_chunks",
        "document_id",
        existing_type=sa.String(),
        nullable=True,
    )
