"""Track the semantic index generation of each knowledge document.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-08
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("index_fingerprint", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_knowledge_documents_index_fingerprint",
        "knowledge_documents",
        ["index_fingerprint"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_documents_index_fingerprint",
        table_name="knowledge_documents",
    )
    op.drop_column("knowledge_documents", "index_fingerprint")
