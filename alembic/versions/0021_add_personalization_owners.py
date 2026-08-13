"""Add explicit personalization fields to their canonical owners.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "copilot_preferences",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "instructions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_copilot_preferences_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_copilot_preferences_user"),
    )
    op.create_index(
        "ix_copilot_preferences_user_id", "copilot_preferences", ["user_id"]
    )
    op.add_column("conversations", sa.Column("guidance_text", sa.Text()))
    op.add_column(
        "conversations", sa.Column("guidance_source_message_id", sa.Integer())
    )
    op.add_column(
        "conversations",
        sa.Column("guidance_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_conversations_guidance_version", "conversations", "guidance_version >= 0"
    )
    op.add_column("interview_records", sa.Column("debrief_guidance_text", sa.Text()))
    op.add_column(
        "interview_records",
        sa.Column("debrief_guidance_source_message_id", sa.Integer()),
    )
    op.add_column(
        "interview_records",
        sa.Column(
            "debrief_guidance_version",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_interview_records_debrief_guidance_version",
        "interview_records",
        "debrief_guidance_version >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_interview_records_debrief_guidance_version",
        "interview_records",
        type_="check",
    )
    op.drop_column("interview_records", "debrief_guidance_version")
    op.drop_column("interview_records", "debrief_guidance_source_message_id")
    op.drop_column("interview_records", "debrief_guidance_text")
    op.drop_constraint(
        "ck_conversations_guidance_version", "conversations", type_="check"
    )
    op.drop_column("conversations", "guidance_version")
    op.drop_column("conversations", "guidance_source_message_id")
    op.drop_column("conversations", "guidance_text")
    op.drop_index("ix_copilot_preferences_user_id", table_name="copilot_preferences")
    op.drop_table("copilot_preferences")
