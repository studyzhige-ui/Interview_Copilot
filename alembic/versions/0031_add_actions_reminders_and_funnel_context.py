"""Add typed NextAction links, reminder settings, and funnel snapshots.

Revision ID: 0031
Revises: 0030
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.drop_constraint("ck_next_actions_source_kind", "next_actions", type_="check")
    op.create_check_constraint(
        "ck_next_actions_source_kind",
        "next_actions",
        "source_kind IN ('user_request', 'process_event', 'agent_suggestion', "
        "'copilot_preference', 'offer')",
    )
    op.add_column(
        "process_events",
        sa.Column(
            "analysis_context_json",
            _jsonb(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.add_column(
        "next_actions",
        sa.Column("interview_record_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "next_actions", sa.Column("offer_id", sa.String(length=35), nullable=True)
    )
    op.add_column(
        "next_actions", sa.Column("artifact_id", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "next_actions",
        sa.Column("reminder_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "next_actions",
        sa.Column(
            "reminder_next_attempt_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "next_actions",
        sa.Column("reminder_channel", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "next_actions",
        sa.Column("reminder_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "next_actions",
        sa.Column("reminder_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "next_actions",
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_next_actions_interview",
        "next_actions",
        "interview_records",
        ["interview_record_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_next_actions_offer",
        "next_actions",
        "offers",
        ["offer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_next_actions_artifact",
        "next_actions",
        "artifacts",
        ["artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_next_actions_version", "next_actions", "version >= 0"
    )
    op.create_check_constraint(
        "ck_next_actions_reminder_channel",
        "next_actions",
        "reminder_channel IS NULL OR reminder_channel = 'in_app'",
    )
    op.create_check_constraint(
        "ck_next_actions_reminder_shape",
        "next_actions",
        "(reminder_at IS NULL AND reminder_next_attempt_at IS NULL "
        "AND reminder_channel IS NULL AND reminder_delivered_at IS NULL "
        "AND reminder_dismissed_at IS NULL) OR "
        "(reminder_at IS NOT NULL AND reminder_next_attempt_at IS NOT NULL "
        "AND reminder_channel IS NOT NULL AND status <> 'suggested')",
    )
    op.create_index(
        op.f("ix_next_actions_interview_record_id"),
        "next_actions",
        ["interview_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_next_actions_offer_id"),
        "next_actions",
        ["offer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_next_actions_artifact_id"),
        "next_actions",
        ["artifact_id"],
        unique=False,
    )
    op.create_index(
        "ix_next_actions_reminder_due",
        "next_actions",
        ["reminder_next_attempt_at", "reminder_delivered_at", "status"],
        unique=False,
    )

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "default_channel",
            sa.String(length=24),
            nullable=False,
            server_default="in_app",
        ),
        sa.Column(
            "timezone",
            sa.String(length=80),
            nullable=False,
            server_default="Asia/Shanghai",
        ),
        sa.Column("quiet_start", sa.String(length=5), nullable=True),
        sa.Column("quiet_end", sa.String(length=5), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "default_channel = 'in_app'",
            name="ck_notification_preferences_channel",
        ),
        sa.CheckConstraint(
            "(quiet_start IS NULL AND quiet_end IS NULL) OR "
            "(quiet_start IS NOT NULL AND quiet_end IS NOT NULL)",
            name="ck_notification_preferences_quiet_pair",
        ),
        sa.CheckConstraint("version >= 0", name="ck_notification_preferences_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_index("ix_next_actions_reminder_due", table_name="next_actions")
    op.drop_index(op.f("ix_next_actions_artifact_id"), table_name="next_actions")
    op.drop_index(op.f("ix_next_actions_offer_id"), table_name="next_actions")
    op.drop_index(
        op.f("ix_next_actions_interview_record_id"), table_name="next_actions"
    )
    op.drop_constraint("ck_next_actions_reminder_shape", "next_actions", type_="check")
    op.drop_constraint(
        "ck_next_actions_reminder_channel", "next_actions", type_="check"
    )
    op.drop_constraint("ck_next_actions_version", "next_actions", type_="check")
    op.drop_constraint("fk_next_actions_artifact", "next_actions", type_="foreignkey")
    op.drop_constraint("fk_next_actions_offer", "next_actions", type_="foreignkey")
    op.drop_constraint("fk_next_actions_interview", "next_actions", type_="foreignkey")
    for column in (
        "version",
        "reminder_dismissed_at",
        "reminder_delivered_at",
        "reminder_channel",
        "reminder_next_attempt_at",
        "reminder_at",
        "artifact_id",
        "offer_id",
        "interview_record_id",
    ):
        op.drop_column("next_actions", column)
    op.drop_column("process_events", "analysis_context_json")
    # Preserve historical actions for the older schema.  The legacy enum has no
    # Offer source kind, so degrade it to its nearest non-authoritative source
    # semantics instead of deleting user-visible action history.
    op.execute(
        "UPDATE next_actions SET source_kind = 'agent_suggestion' "
        "WHERE source_kind = 'offer'"
    )
    op.drop_constraint("ck_next_actions_source_kind", "next_actions", type_="check")
    op.create_check_constraint(
        "ck_next_actions_source_kind",
        "next_actions",
        "source_kind IN ('user_request', 'process_event', 'agent_suggestion', "
        "'copilot_preference')",
    )
