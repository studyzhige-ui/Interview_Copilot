"""Add an independent CAS token for Conversation execution mode.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "execution_mode_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_conversations_execution_mode_version",
        "conversations",
        "execution_mode_version >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_conversations_execution_mode_version",
        "conversations",
        type_="check",
    )
    op.drop_column("conversations", "execution_mode_version")
