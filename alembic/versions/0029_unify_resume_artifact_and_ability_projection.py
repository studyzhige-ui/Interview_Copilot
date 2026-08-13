"""Unify personal resumes under Artifact and add reviewable profile candidates.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "artifact_resume_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("parse_version_id", sa.String(length=128), nullable=True),
        sa.Column("legacy_resume_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "parse_status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_artifact_resume_states_parse_status",
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parse_version_id"],
            ["artifact_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id"),
        sa.UniqueConstraint(
            "user_id",
            "legacy_resume_id",
            name="uq_artifact_resume_states_legacy_resume",
        ),
    )
    op.create_index(
        "ix_artifact_resume_states_artifact_id",
        "artifact_resume_states",
        ["artifact_id"],
    )
    op.create_index(
        "ix_artifact_resume_states_user_id",
        "artifact_resume_states",
        ["user_id"],
    )
    op.create_index(
        "ix_artifact_resume_states_parse_version_id",
        "artifact_resume_states",
        ["parse_version_id"],
    )
    op.create_index(
        "ix_artifact_resume_states_user_default",
        "artifact_resume_states",
        ["user_id", "is_default"],
    )
    op.create_index(
        "uq_artifact_resume_states_one_default",
        "artifact_resume_states",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "career_profile_candidate_items",
        sa.Column("id", sa.String(length=37), nullable=False),
        sa.Column("draft_id", sa.String(length=37), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("payload_json", _jsonb(), nullable=False),
        sa.Column("conflict_kind", sa.String(length=24), nullable=False),
        sa.Column("current_value_json", _jsonb(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "item_kind IN ('fact', 'direction')",
            name="ck_career_profile_candidate_items_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="ck_career_profile_candidate_items_status",
        ),
        sa.CheckConstraint(
            "conflict_kind IN ('none', 'duplicate', 'conflict', 'missing_target')",
            name="ck_career_profile_candidate_items_conflict",
        ),
        sa.CheckConstraint(
            "position >= 0 AND version >= 1",
            name="ck_career_profile_candidate_items_shape",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["career_profile_draft_changes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "draft_id",
            "item_kind",
            "position",
            name="uq_career_profile_candidate_items_position",
        ),
    )
    op.create_index(
        "ix_career_profile_candidate_items_draft_id",
        "career_profile_candidate_items",
        ["draft_id"],
    )
    op.create_index(
        "ix_career_profile_candidate_items_draft_status",
        "career_profile_candidate_items",
        ["draft_id", "status"],
    )

    op.drop_constraint(
        "ck_career_profile_drafts_source_kind",
        "career_profile_draft_changes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_career_profile_drafts_source_kind",
        "career_profile_draft_changes",
        "source_kind IN ('artifact_version', 'resume', "
        "'conversation_message', 'model_inference')",
    )

    op.add_column(
        "interview_records",
        sa.Column("resume_artifact_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "interview_records",
        sa.Column(
            "resume_artifact_version_id",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_interview_records_resume_artifact_id_artifacts",
        "interview_records",
        "artifacts",
        ["resume_artifact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_interview_records_resume_artifact_id",
        "interview_records",
        ["resume_artifact_id"],
    )
    op.create_foreign_key(
        "fk_interview_records_resume_artifact_version",
        "interview_records",
        "artifact_versions",
        ["resume_artifact_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_interview_records_resume_artifact_version_id",
        "interview_records",
        ["resume_artifact_version_id"],
    )
    op.add_column(
        "interview_records",
        sa.Column(
            "ability_signal_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_interview_records_ability_signal_generation",
        "interview_records",
        "ability_signal_generation >= 0",
    )

    op.add_column(
        "ability_signals",
        sa.Column("producer_key", sa.String(length=240), nullable=True),
    )
    op.create_unique_constraint(
        "uq_ability_signals_user_producer_key",
        "ability_signals",
        ["user_id", "producer_key"],
    )

    connection = op.get_bind()

    # Resume Artifacts may already have been saved through the general
    # materials page. They keep their exact identities/versions and receive
    # only the resume-specific selection/parse sidecar; no second content
    # owner is created. Mark them pending so a user-triggered retry can form
    # Profile candidates under the new rules.
    connection.execute(
        sa.text(
            "INSERT INTO artifact_resume_states "
            "(id, artifact_id, user_id, is_default, parse_status, parse_error, "
            "parse_version_id, legacy_resume_id, created_at, updated_at) "
            "SELECT 'ars_' || md5(a.id), a.id, a.user_id, FALSE, 'pending', "
            "NULL, v.id, NULL, a.created_at, a.updated_at "
            "FROM artifacts a "
            "JOIN LATERAL (SELECT av.id FROM artifact_versions av "
            "WHERE av.artifact_id = a.id ORDER BY av.version_no DESC LIMIT 1) v "
            "ON TRUE WHERE a.kind = 'resume' "
            "ON CONFLICT (artifact_id) DO NOTHING"
        )
    )

    # Deterministically migrate legacy resume rows into the canonical Artifact
    # aggregate.  Legacy tables stay read-only for rollback/history; every new
    # production path writes only Artifact rows.
    connection.execute(
        sa.text(
            "INSERT INTO artifacts "
            "(id, user_id, kind, creation_key, created_at, updated_at, archived_at) "
            "SELECT 'art_legacy_' || id, user_id, 'resume', "
            "'legacy_resume:' || id, created_at, updated_at, archived_at "
            "FROM resumes ON CONFLICT (id) DO NOTHING"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO artifact_versions "
            "(id, artifact_id, version_no, operation_key, title, content_text, "
            "content_format, file_asset_id, origin_kind, source_message_id, "
            "source_turn_id, source_owner_type, source_owner_id, created_at) "
            "SELECT 'artv_legacy_' || r.id, 'art_legacy_' || r.id, 1, "
            "'legacy_resume:' || r.id, r.title, r.raw_text_snapshot, 'plain_text', "
            "r.file_asset_id, 'explicit_save', NULL, NULL, 'legacy_resume', r.id, "
            "r.created_at FROM resumes r ON CONFLICT (id) DO NOTHING"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO artifact_resume_states "
            "(id, artifact_id, user_id, is_default, parse_status, parse_error, "
            "parse_version_id, legacy_resume_id, created_at, updated_at) "
            "SELECT 'ars_legacy_' || id, 'art_legacy_' || id, user_id, "
            "is_default AND archived_at IS NULL, "
            "CASE WHEN file_asset_id IS NOT NULL OR "
            "NULLIF(BTRIM(COALESCE(raw_text_snapshot, '')), '') IS NOT NULL "
            "THEN 'pending' ELSE 'failed' END, "
            "CASE WHEN file_asset_id IS NULL AND "
            "NULLIF(BTRIM(COALESCE(raw_text_snapshot, '')), '') IS NULL "
            "THEN COALESCE(parse_error, 'No extractable resume source') "
            "ELSE NULL END, "
            "'artv_legacy_' || id, id, created_at, updated_at "
            "FROM resumes ON CONFLICT (artifact_id) DO NOTHING"
        )
    )
    # Preserve a legacy explicit default when one exists. Otherwise select one
    # active canonical resume deterministically for every user.
    connection.execute(
        sa.text(
            "UPDATE artifact_resume_states s SET is_default = TRUE "
            "WHERE s.id IN ("
            "SELECT DISTINCT ON (s2.user_id) s2.id "
            "FROM artifact_resume_states s2 "
            "JOIN artifacts a2 ON a2.id = s2.artifact_id "
            "WHERE a2.archived_at IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM artifact_resume_states d "
            "JOIN artifacts ad ON ad.id = d.artifact_id "
            "WHERE d.user_id = s2.user_id AND d.is_default "
            "AND ad.archived_at IS NULL) "
            "ORDER BY s2.user_id, a2.updated_at DESC, a2.id DESC)"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE interview_records i SET resume_artifact_id = s.artifact_id, "
            "resume_artifact_version_id = s.parse_version_id "
            "FROM artifact_resume_states s WHERE i.resume_id = s.legacy_resume_id"
        )
    )

    # Existing drafts gain item rows without changing their acceptance state.
    connection.execute(
        sa.text(
            "INSERT INTO career_profile_candidate_items "
            "(id, draft_id, item_kind, position, payload_json, conflict_kind, "
            "current_value_json, status, resolution_note, version, created_at, resolved_at) "
            "SELECT 'cpci_' || md5(d.id || ':fact:' || x.ord), d.id, 'fact', "
            "x.ord - 1, x.value, 'none', NULL, d.status, d.resolution_note, "
            "d.version, d.created_at, d.resolved_at "
            "FROM career_profile_draft_changes d "
            "CROSS JOIN LATERAL jsonb_array_elements(d.proposed_facts_json) "
            "WITH ORDINALITY AS x(value, ord) ON CONFLICT DO NOTHING"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO career_profile_candidate_items "
            "(id, draft_id, item_kind, position, payload_json, conflict_kind, "
            "current_value_json, status, resolution_note, version, created_at, resolved_at) "
            "SELECT 'cpci_' || md5(d.id || ':direction:' || x.ord), d.id, 'direction', "
            "x.ord - 1, x.value, 'none', NULL, d.status, d.resolution_note, "
            "d.version, d.created_at, d.resolved_at "
            "FROM career_profile_draft_changes d "
            "CROSS JOIN LATERAL jsonb_array_elements(d.proposed_directions_json) "
            "WITH ORDINALITY AS x(value, ord) ON CONFLICT DO NOTHING"
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ability_signals_user_producer_key", "ability_signals", type_="unique"
    )
    op.drop_column("ability_signals", "producer_key")
    op.drop_constraint(
        "ck_interview_records_ability_signal_generation",
        "interview_records",
        type_="check",
    )
    op.drop_column("interview_records", "ability_signal_generation")
    op.drop_index(
        "ix_interview_records_resume_artifact_version_id",
        table_name="interview_records",
    )
    op.drop_constraint(
        "fk_interview_records_resume_artifact_version",
        "interview_records",
        type_="foreignkey",
    )
    op.drop_column("interview_records", "resume_artifact_version_id")
    op.drop_index(
        "ix_interview_records_resume_artifact_id", table_name="interview_records"
    )
    op.drop_constraint(
        "fk_interview_records_resume_artifact_id_artifacts",
        "interview_records",
        type_="foreignkey",
    )
    op.drop_column("interview_records", "resume_artifact_id")
    op.drop_constraint(
        "ck_career_profile_drafts_source_kind",
        "career_profile_draft_changes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_career_profile_drafts_source_kind",
        "career_profile_draft_changes",
        "source_kind IN ('resume', 'conversation_message', 'model_inference')",
    )
    op.drop_table("career_profile_candidate_items")
    op.execute(
        sa.text("DELETE FROM artifacts WHERE creation_key LIKE 'legacy_resume:%'")
    )
    op.drop_index(
        "uq_artifact_resume_states_one_default",
        table_name="artifact_resume_states",
    )
    op.drop_table("artifact_resume_states")
