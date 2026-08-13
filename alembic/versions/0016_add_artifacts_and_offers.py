"""Add versioned artifacts and the current final offer projection.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("creation_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "creation_key", name="uq_artifacts_user_creation_key"
        ),
    )
    op.create_index("ix_artifacts_user_id", "artifacts", ["user_id"])
    op.create_index("ix_artifacts_kind", "artifacts", ["kind"])
    op.create_index(
        "ix_artifacts_user_kind_archived",
        "artifacts",
        ["user_id", "kind", "archived_at"],
    )

    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_format", sa.String(length=64), nullable=False),
        sa.Column("file_asset_id", sa.String(), nullable=True),
        sa.Column("origin_kind", sa.String(length=32), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("source_turn_id", sa.String(length=128), nullable=True),
        sa.Column("source_owner_type", sa.String(length=64), nullable=True),
        sa.Column("source_owner_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["artifacts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["file_asset_id"], ["file_assets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "version_no",
            name="uq_artifact_versions_artifact_number",
        ),
        sa.UniqueConstraint(
            "artifact_id",
            "operation_key",
            name="uq_artifact_versions_artifact_operation",
        ),
    )
    op.create_index(
        "ix_artifact_versions_artifact_id", "artifact_versions", ["artifact_id"]
    )
    op.create_index(
        "ix_artifact_versions_file_asset_id", "artifact_versions", ["file_asset_id"]
    )
    op.create_index(
        "ix_artifact_versions_artifact_created",
        "artifact_versions",
        ["artifact_id", "created_at"],
    )

    op.create_table(
        "artifact_job_relations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("job_opportunity_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["artifacts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "job_opportunity_id",
            name="uq_artifact_job_relations_pair",
        ),
    )
    op.create_index(
        "ix_artifact_job_relations_user_id", "artifact_job_relations", ["user_id"]
    )
    op.create_index(
        "ix_artifact_job_relations_artifact_id",
        "artifact_job_relations",
        ["artifact_id"],
    )
    op.create_index(
        "ix_artifact_job_relations_user_job",
        "artifact_job_relations",
        ["user_id", "job_opportunity_id"],
    )

    op.create_table(
        "artifact_submission_snapshots",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.String(length=128), nullable=False),
        sa.Column("job_opportunity_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_version_id", sa.String(length=128), nullable=False),
        sa.Column("basis", sa.String(length=32), nullable=False),
        sa.Column("confirmation_message_id", sa.Integer(), nullable=True),
        sa.Column("receipt_owner_type", sa.String(length=64), nullable=True),
        sa.Column("receipt_owner_id", sa.String(length=128), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["artifacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"], ["artifact_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "operation_key",
            name="uq_artifact_submissions_user_operation",
        ),
    )
    op.create_index(
        "ix_artifact_submission_snapshots_user_id",
        "artifact_submission_snapshots",
        ["user_id"],
    )
    op.create_index(
        "ix_artifact_submissions_user_job",
        "artifact_submission_snapshots",
        ["user_id", "job_opportunity_id"],
    )
    op.create_index(
        "ix_artifact_submissions_artifact_version",
        "artifact_submission_snapshots",
        ["artifact_id", "artifact_version_id"],
    )

    op.create_table(
        "offers",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("job_opportunity_id", sa.String(length=35), nullable=False),
        sa.Column("terms_json", _jsonb(), nullable=False),
        sa.Column("term_sources_json", _jsonb(), nullable=False),
        sa.Column("source_excerpts_json", _jsonb(), nullable=False),
        sa.Column("creation_operation_key", sa.String(length=128), nullable=False),
        sa.Column(
            "creation_operation_fingerprint", sa.String(length=64), nullable=False
        ),
        sa.Column("last_operation_key", sa.String(length=128), nullable=False),
        sa.Column("last_operation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("last_source_kind", sa.String(length=32), nullable=False),
        sa.Column("last_source_identity", sa.String(length=256), nullable=False),
        sa.Column("last_source_version", sa.String(length=128), nullable=True),
        sa.Column("last_source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_confirmation_source_kind", sa.String(length=32), nullable=True
        ),
        sa.Column(
            "last_confirmation_source_identity", sa.String(length=256), nullable=True
        ),
        sa.Column(
            "last_confirmation_source_version", sa.String(length=128), nullable=True
        ),
        sa.Column(
            "last_confirmation_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "last_source_kind IN ('user_assertion', 'observation', 'tool_result', "
            "'provider_receipt', 'artifact', 'file_asset')",
            name="ck_offers_last_source_kind",
        ),
        sa.CheckConstraint(
            "last_confirmation_source_kind IS NULL OR "
            "last_confirmation_source_kind IN ('user_assertion', 'observation', "
            "'tool_result', 'provider_receipt', 'artifact', 'file_asset')",
            name="ck_offers_confirmation_source_kind",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_opportunity_id", name="uq_offers_job_opportunity"
        ),
        sa.UniqueConstraint(
            "user_id",
            "creation_operation_key",
            name="uq_offers_user_creation_operation",
        ),
    )
    op.create_index("ix_offers_user_id", "offers", ["user_id"])
    op.create_index(
        "ix_offers_job_opportunity_id", "offers", ["job_opportunity_id"]
    )
    op.create_index(
        "ix_offers_user_updated", "offers", ["user_id", "updated_at"]
    )


def downgrade() -> None:
    op.drop_table("offers")
    op.drop_table("artifact_submission_snapshots")
    op.drop_table("artifact_job_relations")
    op.drop_table("artifact_versions")
    op.drop_table("artifacts")
