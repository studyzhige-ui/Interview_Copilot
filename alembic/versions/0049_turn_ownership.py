"""Track turn worker ownership and heartbeat.

Revision ID: 0049_turn_ownership
Revises: 0048_drop_agent_journal_events
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0049_turn_ownership"
down_revision: Union[str, None] = "0048_drop_agent_journal_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversation_turns", sa.Column("owner_id", sa.String(length=128), nullable=True))
    op.add_column("conversation_turns", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    op.create_index("ix_conversation_turns_owner_id", "conversation_turns", ["owner_id"])
    op.create_index("ix_conversation_turns_heartbeat_at", "conversation_turns", ["heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_conversation_turns_heartbeat_at", table_name="conversation_turns")
    op.drop_index("ix_conversation_turns_owner_id", table_name="conversation_turns")
    op.drop_column("conversation_turns", "heartbeat_at")
    op.drop_column("conversation_turns", "owner_id")
