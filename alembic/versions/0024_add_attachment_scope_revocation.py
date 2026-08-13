"""Allow an immutable claimed attachment to leave Conversation read scope.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_attachment_refs",
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attachment_refs_conversation_removed",
        "conversation_attachment_refs",
        ["conversation_id", "removed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_attachment_refs_conversation_removed",
        table_name="conversation_attachment_refs",
    )
    op.drop_column("conversation_attachment_refs", "removed_at")
