"""Persist typed resources for unresolved side-effect fencing.

Revision ID: 0040
Revises: 0039
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_tool_calls",
        sa.Column(
            "resource_identities_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "conversation_deletion_receipts",
        sa.Column(
            "resource_identities_json",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation_deletion_receipts", "resource_identities_json")
    op.drop_column("agent_tool_calls", "resource_identities_json")
