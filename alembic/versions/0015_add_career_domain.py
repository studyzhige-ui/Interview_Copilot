"""Add the confirmed career profile and career-process domain.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "career_profiles",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("personal_facts_json", _jsonb(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_career_profiles_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_career_profiles_user"),
    )

    op.create_table(
        "career_profile_directions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("career_profile_id", sa.String(length=35), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("criteria_json", _jsonb(), nullable=False),
        sa.Column("lifecycle", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("confirmed_source_kind", sa.String(length=32), nullable=False),
        sa.Column("confirmed_source_id", sa.String(length=128), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lifecycle IN ('exploring', 'active', 'paused', 'archived')",
            name="ck_career_profile_directions_lifecycle",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_career_profile_directions_priority"),
        sa.CheckConstraint(
            "confirmed_source_kind IN "
            "('user_edit', 'conversation_message', 'draft_acceptance')",
            name="ck_career_profile_directions_confirmed_source",
        ),
        sa.ForeignKeyConstraint(
            ["career_profile_id"], ["career_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_career_profile_directions_career_profile_id",
        "career_profile_directions",
        ["career_profile_id"],
    )
    op.create_index(
        "ix_career_profile_directions_profile_lifecycle_priority",
        "career_profile_directions",
        ["career_profile_id", "lifecycle", "priority"],
    )

    op.create_table(
        "career_profile_draft_changes",
        sa.Column("id", sa.String(length=37), nullable=False),
        sa.Column("career_profile_id", sa.String(length=35), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("base_profile_version", sa.Integer(), nullable=False),
        sa.Column("proposed_facts_json", _jsonb(), nullable=False),
        sa.Column("proposed_directions_json", _jsonb(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_kind IN ('resume', 'conversation_message', 'model_inference')",
            name="ck_career_profile_drafts_source_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="ck_career_profile_drafts_status",
        ),
        sa.CheckConstraint(
            "base_profile_version >= 1 AND version >= 1",
            name="ck_career_profile_drafts_versions",
        ),
        sa.ForeignKeyConstraint(
            ["career_profile_id"], ["career_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_career_profile_draft_changes_career_profile_id",
        "career_profile_draft_changes",
        ["career_profile_id"],
    )
    op.create_index(
        "ix_career_profile_drafts_profile_status_created",
        "career_profile_draft_changes",
        ["career_profile_id", "status", "created_at"],
    )

    op.create_table(
        "job_opportunities",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("job_title", sa.String(length=300), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("team", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("normalized_source_url", sa.Text(), nullable=True),
        sa.Column("source_provider", sa.String(length=80), nullable=True),
        sa.Column("external_job_id", sa.String(length=200), nullable=True),
        sa.Column("external_application_id", sa.String(length=200), nullable=True),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=300), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "phase IN ('pending_application', 'applied', 'in_process', 'offer')",
            name="ck_job_opportunities_phase",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('rejected', 'withdrawn', 'posting_closed', 'declined_offer', 'accepted')",
            name="ck_job_opportunities_outcome",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_job_opportunities_user_idempotency"
        ),
        sa.UniqueConstraint(
            "user_id",
            "source_provider",
            "external_application_id",
            name="uq_job_opportunities_external_application",
        ),
    )
    op.create_index("ix_job_opportunities_user_id", "job_opportunities", ["user_id"])
    op.create_index(
        "ix_job_opportunities_user_outcome_updated",
        "job_opportunities",
        ["user_id", "outcome", "updated_at"],
    )
    op.create_index(
        "ix_job_opportunities_user_external_job",
        "job_opportunities",
        ["user_id", "source_provider", "external_job_id"],
    )

    op.create_table(
        "process_events",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("job_opportunity_id", sa.String(length=35), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_identity", sa.String(length=256), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("step_summary", sa.String(length=300), nullable=True),
        sa.Column("corrects_event_id", sa.String(length=35), nullable=True),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation IN ('assert', 'retract')", name="ck_process_events_operation"
        ),
        sa.CheckConstraint(
            "kind IN ('tracking_started', 'preparation_started', "
            "'application_submitted', 'application_acknowledged', "
            "'recruiter_contact', 'assessment_invited', 'assessment_completed', "
            "'hiring_step', 'interview_scheduled', 'interview_completed', "
            "'background_check_started', 'offer_received', 'rejected', "
            "'withdrawn', 'posting_closed', 'offer_declined', 'offer_accepted', "
            "'retraction')",
            name="ck_process_events_kind",
        ),
        sa.CheckConstraint(
            "source_kind IN "
            "('user_assertion', 'observation', 'tool_result', 'provider_receipt')",
            name="ck_process_events_source_kind",
        ),
        sa.CheckConstraint(
            "(operation = 'assert' AND kind <> 'retraction') OR "
            "(operation = 'retract' AND kind = 'retraction' "
            "AND corrects_event_id IS NOT NULL)",
            name="ck_process_events_operation_shape",
        ),
        sa.ForeignKeyConstraint(
            ["job_opportunity_id"], ["job_opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["corrects_event_id"],
            ["process_events.id"],
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_opportunity_id",
            "sequence",
            name="uq_process_events_opportunity_sequence",
        ),
        sa.UniqueConstraint(
            "job_opportunity_id",
            "idempotency_key",
            name="uq_process_events_opportunity_idempotency",
        ),
    )
    op.create_index(
        "ix_process_events_job_opportunity_id",
        "process_events",
        ["job_opportunity_id"],
    )
    op.create_index(
        "ix_process_events_opportunity_occurred",
        "process_events",
        ["job_opportunity_id", "occurred_at"],
    )
    op.create_index(
        "ix_process_events_source_identity",
        "process_events",
        ["source_kind", "source_identity"],
    )

    op.create_table(
        "next_actions",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("job_opportunity_id", sa.String(length=35), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("time_kind", sa.String(length=16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_time_text", sa.String(length=300), nullable=True),
        sa.Column("source_timezone", sa.String(length=80), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_identity", sa.String(length=256), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_source_kind", sa.String(length=40), nullable=True),
        sa.Column("planned_source_identity", sa.String(length=256), nullable=True),
        sa.Column("planned_source_version", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_source_kind", sa.String(length=40), nullable=True),
        sa.Column("resolution_source_identity", sa.String(length=256), nullable=True),
        sa.Column("resolution_source_version", sa.String(length=128), nullable=True),
        sa.Column("close_reason", sa.String(length=300), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('suggested', 'planned', 'done', 'closed')",
            name="ck_next_actions_status",
        ),
        sa.CheckConstraint(
            "time_kind IN ('fixed', 'deadline', 'flexible')",
            name="ck_next_actions_time_kind",
        ),
        sa.CheckConstraint(
            "source_kind IN "
            "('user_request', 'process_event', 'agent_suggestion', 'copilot_preference')",
            name="ck_next_actions_source_kind",
        ),
        sa.CheckConstraint(
            "(time_kind = 'fixed' AND starts_at IS NOT NULL AND due_at IS NULL "
            "AND (ends_at IS NULL OR ends_at >= starts_at)) OR "
            "(time_kind = 'deadline' AND due_at IS NOT NULL AND starts_at IS NULL "
            "AND ends_at IS NULL) OR (time_kind = 'flexible' AND starts_at IS NULL "
            "AND ends_at IS NULL AND due_at IS NULL)",
            name="ck_next_actions_time_shape",
        ),
        sa.CheckConstraint(
            "time_kind = 'flexible' OR "
            "(original_time_text IS NOT NULL AND source_timezone IS NOT NULL)",
            name="ck_next_actions_time_provenance",
        ),
        sa.CheckConstraint(
            "planned_source_kind IS NULL OR planned_source_kind IN "
            "('user_assertion', 'process_event', 'tool_result', "
            "'application_service_result', 'copilot_preference')",
            name="ck_next_actions_planned_source_kind",
        ),
        sa.CheckConstraint(
            "resolution_source_kind IS NULL OR resolution_source_kind IN "
            "('user_assertion', 'process_event', 'tool_result', "
            "'application_service_result', 'copilot_preference')",
            name="ck_next_actions_resolution_source_kind",
        ),
        sa.CheckConstraint(
            "(planned_at IS NULL AND planned_source_kind IS NULL "
            "AND planned_source_identity IS NULL AND planned_source_version IS NULL) "
            "OR (planned_at IS NOT NULL AND planned_source_kind IS NOT NULL "
            "AND planned_source_identity IS NOT NULL)",
            name="ck_next_actions_planning_provenance",
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL AND resolution_source_kind IS NULL "
            "AND resolution_source_identity IS NULL "
            "AND resolution_source_version IS NULL) OR "
            "(resolved_at IS NOT NULL AND resolution_source_kind IS NOT NULL "
            "AND resolution_source_identity IS NOT NULL)",
            name="ck_next_actions_resolution_provenance",
        ),
        sa.CheckConstraint(
            "(status = 'suggested' AND planned_at IS NULL AND resolved_at IS NULL) OR "
            "(status = 'planned' AND planned_at IS NOT NULL AND resolved_at IS NULL) OR "
            "(status IN ('done', 'closed') AND resolved_at IS NOT NULL)",
            name="ck_next_actions_status_shape",
        ),
        sa.CheckConstraint(
            "(status = 'closed' AND close_reason IS NOT NULL) OR "
            "(status <> 'closed' AND close_reason IS NULL)",
            name="ck_next_actions_close_reason",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["job_opportunity_id"], ["job_opportunities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_next_actions_user_idempotency"
        ),
    )
    op.create_index("ix_next_actions_user_id", "next_actions", ["user_id"])
    op.create_index(
        "ix_next_actions_job_opportunity_id",
        "next_actions",
        ["job_opportunity_id"],
    )
    op.create_index(
        "ix_next_actions_user_status_updated",
        "next_actions",
        ["user_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_next_actions_opportunity_status",
        "next_actions",
        ["job_opportunity_id", "status"],
    )

    op.create_table(
        "ability_signals",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("limitations", sa.Text(), nullable=True),
        sa.Column("scope_kind", sa.String(length=32), nullable=False),
        sa.Column("scope_ref_id", sa.String(length=128), nullable=True),
        sa.Column("formed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rubric_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_signal_id", sa.String(length=35), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ability_signals_confidence_range",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disputed', 'invalidated', 'superseded')",
            name="ck_ability_signals_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_ability_signals_version"),
        sa.CheckConstraint(
            "scope_kind IN "
            "('general', 'career_direction', 'job_opportunity', 'interview_record')",
            name="ck_ability_signals_scope_kind",
        ),
        sa.CheckConstraint(
            "(scope_kind = 'general' AND scope_ref_id IS NULL) OR "
            "(scope_kind <> 'general' AND scope_ref_id IS NOT NULL)",
            name="ck_ability_signals_scope_shape",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["supersedes_signal_id"], ["ability_signals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ability_signals_user_id", "ability_signals", ["user_id"])
    op.create_index(
        "ix_ability_signals_supersedes_signal_id",
        "ability_signals",
        ["supersedes_signal_id"],
    )
    op.create_index(
        "ix_ability_signals_user_status_formed",
        "ability_signals",
        ["user_id", "status", "formed_at"],
    )
    op.create_index(
        "ix_ability_signals_user_topic_type",
        "ability_signals",
        ["user_id", "topic", "signal_type"],
    )

    op.create_table(
        "ability_signal_source_refs",
        sa.Column("id", sa.String(length=37), nullable=False),
        sa.Column("ability_signal_id", sa.String(length=35), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('interview_record', 'interview_qa', "
            "'conversation_message', 'agent_tool_call', 'process_event', "
            "'artifact_version')",
            name="ck_ability_signal_sources_kind",
        ),
        sa.ForeignKeyConstraint(
            ["ability_signal_id"], ["ability_signals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ability_signal_id",
            "source_kind",
            "source_id",
            name="uq_ability_signal_sources_identity",
        ),
    )
    op.create_index(
        "ix_ability_signal_source_refs_ability_signal_id",
        "ability_signal_source_refs",
        ["ability_signal_id"],
    )
    op.create_index(
        "ix_ability_signal_sources_owner",
        "ability_signal_source_refs",
        ["source_kind", "source_id"],
    )

    # Legacy ability rows were a mixed Memory-owned projection.  Migrate only
    # rows whose source pointers can be mapped to the closed canonical owner
    # set; rows without usable sources stay quarantined in the legacy table and
    # never enter Context or user-facing diagnostics.  The new id is derived
    # from the legacy primary key, making an interrupted/replayed migration
    # deterministic instead of duplicating inferred state.
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if "memory_ability_states" in inspector.get_table_names():
        legacy_rows = connection.execute(
            sa.text(
                "SELECT id, user_id, topic, skill_type, mastery_level, "
                "ability_score, score_version, summary, evidence_refs_json, "
                "last_evidence_at, created_at, updated_at "
                "FROM memory_ability_states WHERE archived_at IS NULL"
            )
        ).mappings()
        allowed_source_kinds = {
            "interview_record",
            "interview_qa",
            "conversation_message",
            "agent_tool_call",
            "process_event",
            "artifact_version",
        }
        for legacy in legacy_rows:
            raw_sources = legacy["evidence_refs_json"] or []
            if not isinstance(raw_sources, list):
                continue
            sources: list[tuple[str, str]] = []
            for raw in raw_sources:
                if not isinstance(raw, dict):
                    continue
                kind = str(raw.get("type") or raw.get("kind") or "").strip()
                source_id = str(raw.get("id") or raw.get("source_id") or "").strip()
                if kind in allowed_source_kinds and source_id:
                    identity = (kind, source_id)
                    if identity not in sources:
                        sources.append(identity)
            if not sources:
                continue
            legacy_id = str(legacy["id"])
            signal_id = "as_legacy_" + legacy_id.removeprefix("mas_")
            formed_at = (
                legacy["last_evidence_at"]
                or legacy["updated_at"]
                or legacy["created_at"]
            )
            connection.execute(
                sa.text(
                    "INSERT INTO ability_signals "
                    "(id, user_id, topic, signal_type, level, score, summary, "
                    "confidence, limitations, scope_kind, scope_ref_id, formed_at, "
                    "rubric_version, status, status_reason, supersedes_signal_id, "
                    "version, created_at, updated_at, status_changed_at) "
                    "VALUES (:id, :user_id, :topic, :signal_type, :level, :score, "
                    ":summary, NULL, :limitations, 'general', NULL, :formed_at, "
                    ":rubric_version, 'active', NULL, NULL, 1, :created_at, "
                    ":updated_at, :status_changed_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": signal_id,
                    "user_id": legacy["user_id"],
                    "topic": legacy["topic"],
                    "signal_type": legacy["skill_type"],
                    "level": legacy["mastery_level"],
                    "score": legacy["ability_score"],
                    "summary": legacy["summary"] or "Legacy inferred ability state",
                    "limitations": "Migrated from a retired inference pipeline.",
                    "formed_at": formed_at,
                    "rubric_version": legacy["score_version"],
                    "created_at": legacy["created_at"] or formed_at,
                    "updated_at": legacy["updated_at"] or formed_at,
                    "status_changed_at": formed_at,
                },
            )
            for index, (kind, source_id) in enumerate(sources):
                source_ref_id = f"assr_legacy_{legacy_id.removeprefix('mas_')}_{index}"
                connection.execute(
                    sa.text(
                        "INSERT INTO ability_signal_source_refs "
                        "(id, ability_signal_id, source_kind, source_id, "
                        "source_version, created_at) "
                        "VALUES (:id, :signal_id, :kind, :source_id, NULL, :created_at) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": source_ref_id,
                        "signal_id": signal_id,
                        "kind": kind,
                        "source_id": source_id,
                        "created_at": formed_at,
                    },
                )


def downgrade() -> None:
    op.drop_table("ability_signal_source_refs")
    op.drop_table("ability_signals")
    op.drop_table("next_actions")
    op.drop_table("process_events")
    op.drop_table("job_opportunities")
    op.drop_table("career_profile_draft_changes")
    op.drop_table("career_profile_directions")
    op.drop_table("career_profiles")
