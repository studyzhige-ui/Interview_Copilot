"""Add VS-01 invitation operations, evidence, and confirmed schedules.

Revision ID: 0043
Revises: 0042
Create Date: 2026-08-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operation_name", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("turn_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("tool_call_id", sa.String(length=256), nullable=True),
        sa.Column("interaction_id", sa.String(length=36), nullable=True),
        sa.Column(
            "request_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'agent_on_behalf', 'automation', "
            "'system_connector')",
            name="ck_application_operations_actor_kind",
        ),
        sa.CheckConstraint(
            "status IN ('started', 'verifying', 'succeeded', 'failed', "
            "'unknown', 'reconciled')",
            name="ck_application_operations_status",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_application_operations_schema_version",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["conversation_turns.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["agent_interactions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "operation_name",
            "idempotency_key",
            name="uq_application_operations_user_name_idempotency",
        ),
    )
    op.create_index(
        "ix_application_operations_user_id",
        "application_operations",
        ["user_id"],
    )
    op.create_index(
        "ix_application_operations_interaction_id",
        "application_operations",
        ["interaction_id"],
    )
    op.create_index(
        "ix_application_operations_turn_created",
        "application_operations",
        ["turn_id", "created_at"],
    )
    op.create_index(
        "ix_application_operations_user_status_updated",
        "application_operations",
        ["user_id", "status", "updated_at"],
    )

    op.create_table(
        "operation_verifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("conclusion", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=64), nullable=False),
        sa.Column(
            "expected_postconditions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "observed_evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("next_reconciliation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "conclusion IN ('pending', 'verified', 'failed', 'unknown', 'reconciled')",
            name="ck_operation_verifications_conclusion",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_operation_verifications_schema_version",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["application_operations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id", name="uq_operation_verifications_operation"
        ),
    )
    op.create_index(
        "ix_operation_verifications_operation_id",
        "operation_verifications",
        ["operation_id"],
    )

    op.create_table(
        "career_domain_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("event_kind", sa.String(length=128), nullable=False),
        sa.Column("event_category", sa.String(length=24), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=True),
        sa.Column(
            "object_references_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("replayable", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_category = 'domain'", name="ck_career_domain_events_category"
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_career_domain_events_schema_version"
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_career_domain_events_sequence"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["application_operations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            "sequence",
            name="uq_career_domain_events_operation_sequence",
        ),
        sa.UniqueConstraint(
            "user_id",
            "event_kind",
            "idempotency_key",
            name="uq_career_domain_events_user_kind_idempotency",
        ),
    )
    op.create_index(
        "ix_career_domain_events_user_id",
        "career_domain_events",
        ["user_id"],
    )
    op.create_index(
        "ix_career_domain_events_operation_id",
        "career_domain_events",
        ["operation_id"],
    )
    op.create_index(
        "ix_career_domain_events_user_occurred",
        "career_domain_events",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_career_domain_events_aggregate",
        "career_domain_events",
        ["aggregate_type", "aggregate_id", "occurred_at"],
    )

    op.create_table(
        "interview_invitation_source_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_identity", sa.String(length=256), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('fixture', 'manual', 'user_message', 'gmail')",
            name="ck_interview_invitation_sources_kind",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_kind",
            "source_identity",
            "source_version",
            name="uq_interview_invitation_source_version",
        ),
    )
    op.create_index(
        "ix_interview_invitation_source_snapshots_user_id",
        "interview_invitation_source_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_interview_invitation_sources_user_observed",
        "interview_invitation_source_snapshots",
        ["user_id", "observed_at"],
    )

    op.create_table(
        "interview_invitation_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("retraction_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('received', 'candidate_registered', "
            "'pending_confirmation', 'confirmed', 'rejected', 'retracted')",
            name="ck_interview_invitation_observations_status",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_interview_invitation_observations_version"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["interview_invitation_source_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_snapshot_id", name="uq_interview_invitation_observation_source"
        ),
    )
    op.create_index(
        "ix_interview_invitation_observations_user_id",
        "interview_invitation_observations",
        ["user_id"],
    )
    op.create_index(
        "ix_interview_invitation_observations_user_status",
        "interview_invitation_observations",
        ["user_id", "status", "updated_at"],
    )

    op.create_table(
        "interview_invitation_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_identity", sa.String(length=256), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "facts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "field_provenance_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "missing_fields_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "conflicts_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("extractor_version", sa.String(length=128), nullable=False),
        sa.Column("resolved_by_interaction_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_operation_id", sa.String(length=36), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('needs_clarification', 'pending_confirmation', "
            "'confirmed', 'rejected', 'superseded')",
            name="ck_interview_invitation_candidates_status",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_interview_invitation_candidates_version"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_interview_invitation_candidates_confidence",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["interview_invitation_observations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_interaction_id"],
            ["agent_interactions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_operation_id"],
            ["application_operations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_kind",
            "source_identity",
            "source_version",
            name="uq_interview_invitation_candidate_source",
        ),
    )
    op.create_index(
        "ix_interview_invitation_candidates_user_id",
        "interview_invitation_candidates",
        ["user_id"],
    )
    op.create_index(
        "ix_interview_invitation_candidates_observation_id",
        "interview_invitation_candidates",
        ["observation_id"],
    )
    op.create_index(
        "ix_interview_invitation_candidates_user_status",
        "interview_invitation_candidates",
        ["user_id", "status", "updated_at"],
    )

    op.add_column(
        "job_opportunities",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        "ck_job_opportunities_version", "job_opportunities", "version >= 1"
    )

    op.add_column(
        "interview_records",
        sa.Column("schedule_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "interview_records",
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("original_time_text", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("source_timezone", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("stage_label", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("scheduled_location", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "interview_records", sa.Column("meeting_url", sa.Text(), nullable=True)
    )
    op.add_column(
        "interview_records",
        sa.Column(
            "contact_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "interview_records",
        sa.Column("invitation_source_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("invitation_source_identity", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("invitation_source_version", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("invitation_candidate_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column("invitation_operation_id", sa.String(length=36), nullable=True),
    )
    op.create_check_constraint(
        "ck_interview_records_schedule_version",
        "interview_records",
        "schedule_version >= 0",
    )
    op.create_check_constraint(
        "ck_interview_records_schedule_end_shape",
        "interview_records",
        "scheduled_end_at IS NULL OR scheduled_start_at IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_interview_records_invitation_candidate",
        "interview_records",
        "interview_invitation_candidates",
        ["invitation_candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_interview_records_invitation_operation",
        "interview_records",
        "application_operations",
        ["invitation_operation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_interview_records_invitation_operation",
        "interview_records",
        ["invitation_operation_id"],
    )
    op.create_index(
        "ix_interview_records_invitation_candidate_id",
        "interview_records",
        ["invitation_candidate_id"],
    )
    op.create_index(
        "ix_interview_records_invitation_operation_id",
        "interview_records",
        ["invitation_operation_id"],
    )

    op.create_table(
        "interview_invitation_evidence_refs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("source_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("interview_record_id", sa.String(), nullable=False),
        sa.Column("process_event_id", sa.String(length=35), nullable=False),
        sa.Column("field_name", sa.String(length=80), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_identity", sa.String(length=256), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=True),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["application_operations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["interview_invitation_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"],
            ["interview_invitation_source_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["interview_record_id"], ["interview_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["process_event_id"], ["process_events.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id",
            "field_name",
            "source_kind",
            "source_identity",
            "source_version",
            name="uq_interview_invitation_evidence_binding",
        ),
    )
    op.create_index(
        "ix_interview_invitation_evidence_refs_user_id",
        "interview_invitation_evidence_refs",
        ["user_id"],
    )
    op.create_index(
        "ix_interview_invitation_evidence_refs_operation_id",
        "interview_invitation_evidence_refs",
        ["operation_id"],
    )
    op.create_index(
        "ix_interview_invitation_evidence_refs_interview_record_id",
        "interview_invitation_evidence_refs",
        ["interview_record_id"],
    )
    op.create_index(
        "ix_interview_invitation_evidence_interview",
        "interview_invitation_evidence_refs",
        ["interview_record_id", "created_at"],
    )

    op.drop_constraint(
        "ck_agent_interactions_kind", "agent_interactions", type_="check"
    )
    op.add_column(
        "agent_interactions",
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "agent_interactions",
        sa.Column("resolution_identity", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "agent_interactions",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_agent_interactions_kind",
        "agent_interactions",
        "kind IN ('clarification', 'connection', 'approval', "
        "'fact_confirmation', 'profile_update_confirmation', 'client_readiness')",
    )
    op.create_check_constraint(
        "ck_agent_interactions_schema_version",
        "agent_interactions",
        "schema_version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_agent_interactions_schema_version", "agent_interactions", type_="check"
    )
    op.drop_constraint(
        "ck_agent_interactions_kind", "agent_interactions", type_="check"
    )
    op.create_check_constraint(
        "ck_agent_interactions_kind",
        "agent_interactions",
        "kind IN ('clarification', 'connection', 'approval', 'client_readiness')",
    )
    op.drop_column("agent_interactions", "expires_at")
    op.drop_column("agent_interactions", "resolution_identity")
    op.drop_column("agent_interactions", "schema_version")

    op.drop_index(
        "ix_interview_invitation_evidence_interview",
        table_name="interview_invitation_evidence_refs",
    )
    op.drop_index(
        "ix_interview_invitation_evidence_refs_interview_record_id",
        table_name="interview_invitation_evidence_refs",
    )
    op.drop_index(
        "ix_interview_invitation_evidence_refs_operation_id",
        table_name="interview_invitation_evidence_refs",
    )
    op.drop_index(
        "ix_interview_invitation_evidence_refs_user_id",
        table_name="interview_invitation_evidence_refs",
    )
    op.drop_table("interview_invitation_evidence_refs")

    op.drop_index(
        "ix_interview_records_invitation_operation_id", table_name="interview_records"
    )
    op.drop_index(
        "ix_interview_records_invitation_candidate_id", table_name="interview_records"
    )
    op.drop_constraint(
        "uq_interview_records_invitation_operation",
        "interview_records",
        type_="unique",
    )
    op.drop_constraint(
        "fk_interview_records_invitation_operation",
        "interview_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_interview_records_invitation_candidate",
        "interview_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_interview_records_schedule_end_shape",
        "interview_records",
        type_="check",
    )
    op.drop_constraint(
        "ck_interview_records_schedule_version",
        "interview_records",
        type_="check",
    )
    for column in (
        "invitation_operation_id",
        "invitation_candidate_id",
        "invitation_source_version",
        "invitation_source_identity",
        "invitation_source_kind",
        "contact_json",
        "meeting_url",
        "scheduled_location",
        "stage_label",
        "source_timezone",
        "original_time_text",
        "scheduled_end_at",
        "scheduled_start_at",
        "schedule_version",
    ):
        op.drop_column("interview_records", column)

    op.drop_constraint(
        "ck_job_opportunities_version", "job_opportunities", type_="check"
    )
    op.drop_column("job_opportunities", "version")

    op.drop_index(
        "ix_interview_invitation_candidates_user_status",
        table_name="interview_invitation_candidates",
    )
    op.drop_index(
        "ix_interview_invitation_candidates_observation_id",
        table_name="interview_invitation_candidates",
    )
    op.drop_index(
        "ix_interview_invitation_candidates_user_id",
        table_name="interview_invitation_candidates",
    )
    op.drop_table("interview_invitation_candidates")

    op.drop_index(
        "ix_interview_invitation_observations_user_status",
        table_name="interview_invitation_observations",
    )
    op.drop_index(
        "ix_interview_invitation_observations_user_id",
        table_name="interview_invitation_observations",
    )
    op.drop_table("interview_invitation_observations")

    op.drop_index(
        "ix_interview_invitation_sources_user_observed",
        table_name="interview_invitation_source_snapshots",
    )
    op.drop_index(
        "ix_interview_invitation_source_snapshots_user_id",
        table_name="interview_invitation_source_snapshots",
    )
    op.drop_table("interview_invitation_source_snapshots")

    op.drop_index(
        "ix_career_domain_events_aggregate", table_name="career_domain_events"
    )
    op.drop_index(
        "ix_career_domain_events_user_occurred", table_name="career_domain_events"
    )
    op.drop_index(
        "ix_career_domain_events_operation_id", table_name="career_domain_events"
    )
    op.drop_index("ix_career_domain_events_user_id", table_name="career_domain_events")
    op.drop_table("career_domain_events")

    op.drop_index(
        "ix_operation_verifications_operation_id",
        table_name="operation_verifications",
    )
    op.drop_table("operation_verifications")

    op.drop_index(
        "ix_application_operations_user_status_updated",
        table_name="application_operations",
    )
    op.drop_index(
        "ix_application_operations_turn_created", table_name="application_operations"
    )
    op.drop_index(
        "ix_application_operations_interaction_id",
        table_name="application_operations",
    )
    op.drop_index(
        "ix_application_operations_user_id", table_name="application_operations"
    )
    op.drop_table("application_operations")
