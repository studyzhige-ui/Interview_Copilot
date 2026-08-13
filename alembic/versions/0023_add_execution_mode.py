"""Persist Standard/Auto at user, Conversation, submission, and Turn seams.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "default_execution_mode",
            sa.String(length=16),
            nullable=False,
            server_default="standard",
        ),
    )
    op.create_check_constraint(
        "ck_users_default_execution_mode",
        "users",
        "default_execution_mode IN ('standard', 'auto')",
    )

    for table, constraint in (
        ("conversations", "ck_conversations_execution_mode"),
        ("pending_submissions", "ck_pending_submissions_execution_mode"),
        ("conversation_turns", "ck_conversation_turns_execution_mode"),
    ):
        op.add_column(
            table,
            sa.Column(
                "execution_mode",
                sa.String(length=16),
                nullable=False,
                server_default="standard",
            ),
        )
        op.create_check_constraint(
            constraint,
            table,
            "execution_mode IN ('standard', 'auto')",
        )


def downgrade() -> None:
    for table, constraint in (
        ("conversation_turns", "ck_conversation_turns_execution_mode"),
        ("pending_submissions", "ck_pending_submissions_execution_mode"),
        ("conversations", "ck_conversations_execution_mode"),
    ):
        op.drop_constraint(constraint, table, type_="check")
        op.drop_column(table, "execution_mode")
    op.drop_constraint("ck_users_default_execution_mode", "users", type_="check")
    op.drop_column("users", "default_execution_mode")
