"""Make mock runtime an ephemeral active-interview cursor.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Completed/processing rows belong to the retired runtime state machine;
    # corrupt rows without a conversation cannot be resumed.
    op.execute(
        "DELETE FROM mock_interview_runtime "
        "WHERE status <> 'in_progress' OR conversation_id IS NULL"
    )
    # Historic application checks were not a database constraint, so retain
    # only the newest active row if concurrent starts ever created duplicates.
    op.execute(
        "DELETE FROM mock_interview_runtime AS older "
        "USING mock_interview_runtime AS newer "
        "WHERE older.user_id = newer.user_id AND ("
        "older.last_activity_at < newer.last_activity_at OR ("
        "older.last_activity_at = newer.last_activity_at AND older.id < newer.id"
        "))"
    )

    op.drop_index(
        "ix_mock_runtime_user_status_activity",
        table_name="mock_interview_runtime",
    )
    op.drop_index(
        op.f("ix_mock_interview_runtime_status"),
        table_name="mock_interview_runtime",
    )
    op.drop_index(
        op.f("ix_mock_interview_runtime_user_id"),
        table_name="mock_interview_runtime",
    )
    op.drop_index(
        op.f("ix_mock_interview_runtime_interview_record_id"),
        table_name="mock_interview_runtime",
    )
    op.drop_constraint(
        "mock_interview_runtime_pkey",
        "mock_interview_runtime",
        type_="primary",
    )

    op.alter_column("mock_interview_runtime", "conversation_id", nullable=False)
    for column in (
        "id",
        "status",
        "stage_index",
        "current_question_text",
        "plan_template_key",
        "voice_mode",
        "started_at",
        "ended_at",
        "updated_at",
    ):
        op.drop_column("mock_interview_runtime", column)

    op.create_primary_key(
        "mock_interview_runtime_pkey",
        "mock_interview_runtime",
        ["interview_record_id"],
    )
    op.create_unique_constraint(
        "uq_mock_interview_runtime_user_id",
        "mock_interview_runtime",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_mock_interview_runtime_user_id",
        "mock_interview_runtime",
        type_="unique",
    )
    op.drop_constraint(
        "mock_interview_runtime_pkey",
        "mock_interview_runtime",
        type_="primary",
    )

    op.add_column("mock_interview_runtime", sa.Column("id", sa.String(), nullable=True))
    op.execute(
        "UPDATE mock_interview_runtime SET id = "
        "'mir_' || substr(md5(random()::text || interview_record_id), 1, 12)"
    )
    op.alter_column("mock_interview_runtime", "id", nullable=False)
    op.add_column(
        "mock_interview_runtime",
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="in_progress",
        ),
    )
    op.add_column(
        "mock_interview_runtime",
        sa.Column("stage_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mock_interview_runtime", sa.Column("current_question_text", sa.Text())
    )
    op.add_column(
        "mock_interview_runtime",
        sa.Column(
            "plan_template_key",
            sa.String(),
            nullable=False,
            server_default="general",
        ),
    )
    op.add_column(
        "mock_interview_runtime",
        sa.Column(
            "voice_mode", sa.String(), nullable=False, server_default="hybrid"
        ),
    )
    op.add_column(
        "mock_interview_runtime",
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "mock_interview_runtime", sa.Column("ended_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "mock_interview_runtime",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_primary_key(
        "mock_interview_runtime_pkey", "mock_interview_runtime", ["id"]
    )
    op.create_index(
        op.f("ix_mock_interview_runtime_interview_record_id"),
        "mock_interview_runtime",
        ["interview_record_id"],
    )
    op.create_index(
        op.f("ix_mock_interview_runtime_user_id"),
        "mock_interview_runtime",
        ["user_id"],
    )
    op.create_index(
        op.f("ix_mock_interview_runtime_status"),
        "mock_interview_runtime",
        ["status"],
    )
    op.create_index(
        "ix_mock_runtime_user_status_activity",
        "mock_interview_runtime",
        ["user_id", "status", "last_activity_at"],
    )
