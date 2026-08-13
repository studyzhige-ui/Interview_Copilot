"""Add Gmail Observation intake, source snapshots, and task review cards.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "gmail_integration_accounts",
        sa.Column("history_cursor", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "gmail_integration_accounts",
        sa.Column(
            "history_cursor_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "gmail_integration_accounts",
        sa.Column(
            "last_observation_sync_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "gmail_integration_accounts",
        sa.Column(
            "last_observation_sync_error_code", sa.String(length=64), nullable=True
        ),
    )

    op.create_table(
        "gmail_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("gmail_account_id", sa.String(length=36), nullable=False),
        sa.Column("provider_message_id", sa.String(length=256), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=256), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("candidate_event_kind", sa.String(length=40), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("unique_match", sa.Boolean(), nullable=True),
        sa.Column("analysis_summary", sa.Text(), nullable=True),
        sa.Column("matched_job_opportunity_id", sa.String(length=35), nullable=True),
        sa.Column("applied_process_event_id", sa.String(length=35), nullable=True),
        sa.Column("retraction_process_event_id", sa.String(length=35), nullable=True),
        sa.Column("notification_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('unreviewed', 'pending_confirmation', 'applied', "
            "'dismissed', 'retracted')",
            name="ck_gmail_observations_status",
        ),
        sa.CheckConstraint(
            "classification_confidence IS NULL OR "
            "(classification_confidence >= 0 AND classification_confidence <= 1)",
            name="ck_gmail_observations_confidence",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["gmail_account_id"],
            ["gmail_integration_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["matched_job_opportunity_id"],
            ["job_opportunities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["applied_process_event_id"],
            ["process_events.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["retraction_process_event_id"],
            ["process_events.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gmail_account_id",
            "provider_message_id",
            name="uq_gmail_observations_account_message",
        ),
    )
    op.create_index(
        "ix_gmail_observations_user_id",
        "gmail_observations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_gmail_observations_gmail_account_id",
        "gmail_observations",
        ["gmail_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_gmail_observations_user_status_observed",
        "gmail_observations",
        ["user_id", "status", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_gmail_observations_opportunity",
        "gmail_observations",
        ["matched_job_opportunity_id", "observed_at"],
        unique=False,
    )

    op.create_table(
        "gmail_observation_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_version", sa.String(length=128), nullable=False),
        sa.Column("provider_history_id", sa.String(length=256), nullable=False),
        sa.Column("provider_message_id", sa.String(length=256), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=256), nullable=False),
        sa.Column("content_available", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("from_hint", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("snippet", sa.String(length=1000), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["gmail_observations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "observation_id",
            "snapshot_version",
            name="uq_gmail_observation_snapshots_version",
        ),
    )
    op.create_index(
        "ix_gmail_observation_snapshots_observation_id",
        "gmail_observation_snapshots",
        ["observation_id"],
        unique=False,
    )
    op.create_index(
        "ix_gmail_observation_snapshots_observation_observed",
        "gmail_observation_snapshots",
        ["observation_id", "observed_at"],
        unique=False,
    )

    op.create_table(
        "gmail_observation_review_cards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("persistent_task_id", sa.String(length=35), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("source_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("candidate_event_kind", sa.String(length=40), nullable=False),
        sa.Column("candidate_opportunity_id", sa.String(length=35), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("step_summary", sa.String(length=300), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("unique_match", sa.Boolean(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("new_opportunity_json", sa.JSON(), nullable=True),
        sa.Column("process_event_id", sa.String(length=35), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("user_request_identity", sa.String(length=256), nullable=True),
        sa.Column("user_request_version", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'skipped')",
            name="ck_gmail_observation_review_cards_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_gmail_observation_review_cards_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["persistent_task_id"], ["persistent_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["gmail_observations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["gmail_observation_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_opportunity_id"],
            ["job_opportunities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["process_event_id"], ["process_events.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "persistent_task_id",
            "observation_id",
            name="uq_gmail_observation_review_cards_task_observation",
        ),
    )
    op.create_index(
        "ix_gmail_observation_review_cards_persistent_task_id",
        "gmail_observation_review_cards",
        ["persistent_task_id"],
        unique=False,
    )
    op.create_index(
        "ix_gmail_observation_review_cards_observation_id",
        "gmail_observation_review_cards",
        ["observation_id"],
        unique=False,
    )
    op.create_index(
        "ix_gmail_observation_review_cards_task_status_created",
        "gmail_observation_review_cards",
        ["persistent_task_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gmail_observation_review_cards_task_status_created",
        table_name="gmail_observation_review_cards",
    )
    op.drop_index(
        "ix_gmail_observation_review_cards_observation_id",
        table_name="gmail_observation_review_cards",
    )
    op.drop_index(
        "ix_gmail_observation_review_cards_persistent_task_id",
        table_name="gmail_observation_review_cards",
    )
    op.drop_table("gmail_observation_review_cards")
    op.drop_index(
        "ix_gmail_observation_snapshots_observation_observed",
        table_name="gmail_observation_snapshots",
    )
    op.drop_index(
        "ix_gmail_observation_snapshots_observation_id",
        table_name="gmail_observation_snapshots",
    )
    op.drop_table("gmail_observation_snapshots")
    op.drop_index("ix_gmail_observations_opportunity", table_name="gmail_observations")
    op.drop_index(
        "ix_gmail_observations_user_status_observed",
        table_name="gmail_observations",
    )
    op.drop_index(
        "ix_gmail_observations_gmail_account_id",
        table_name="gmail_observations",
    )
    op.drop_index("ix_gmail_observations_user_id", table_name="gmail_observations")
    op.drop_table("gmail_observations")
    op.drop_column("gmail_integration_accounts", "last_observation_sync_error_code")
    op.drop_column("gmail_integration_accounts", "last_observation_sync_at")
    op.drop_column("gmail_integration_accounts", "history_cursor_updated_at")
    op.drop_column("gmail_integration_accounts", "history_cursor")
