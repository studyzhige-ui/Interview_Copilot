"""Add append-only JobOpportunity-owned JD snapshots.

Revision ID: 0039
Revises: 0038
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_description_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_opportunity_id", sa.String(length=35), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("canonical_content", sa.Text(), nullable=False),
        sa.Column("content_checksum", sa.String(length=64), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_identity", sa.String(length=256), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("creation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('tool_result', 'typed_product_ui')",
            name="ck_job_description_snapshots_source_kind",
        ),
        sa.CheckConstraint(
            "length(canonical_content) > 0 AND length(canonical_content) <= 120000",
            name="ck_job_description_snapshots_content_length",
        ),
        sa.ForeignKeyConstraint(
            ["job_opportunity_id"],
            ["job_opportunities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_opportunity_id",
            "version",
            name="uq_job_description_snapshots_opportunity_version",
        ),
        sa.UniqueConstraint(
            "job_opportunity_id",
            "idempotency_key",
            name="uq_job_description_snapshots_opportunity_idempotency",
        ),
    )
    op.create_index(
        "ix_job_description_snapshots_job_opportunity_id",
        "job_description_snapshots",
        ["job_opportunity_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_description_snapshots_opportunity_observed",
        "job_description_snapshots",
        ["job_opportunity_id", "observed_at", "version"],
        unique=False,
    )
    op.create_index(
        "ix_job_description_snapshots_source_identity",
        "job_description_snapshots",
        ["source_kind", "source_identity", "source_version"],
        unique=False,
    )

    with op.batch_alter_table("process_events") as batch_op:
        batch_op.add_column(
            sa.Column("jd_snapshot_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("jd_snapshot_version", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_process_events_jd_snapshot_id",
            "job_description_snapshots",
            ["jd_snapshot_id"],
            ["id"],
            ondelete="NO ACTION",
        )
        batch_op.create_check_constraint(
            "ck_process_events_jd_snapshot_shape",
            "(jd_snapshot_id IS NULL AND jd_snapshot_version IS NULL) OR "
            "(jd_snapshot_id IS NOT NULL AND jd_snapshot_version IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("process_events") as batch_op:
        batch_op.drop_constraint(
            "ck_process_events_jd_snapshot_shape",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_process_events_jd_snapshot_id",
            type_="foreignkey",
        )
        batch_op.drop_column("jd_snapshot_version")
        batch_op.drop_column("jd_snapshot_id")

    op.drop_index(
        "ix_job_description_snapshots_source_identity",
        table_name="job_description_snapshots",
    )
    op.drop_index(
        "ix_job_description_snapshots_opportunity_observed",
        table_name="job_description_snapshots",
    )
    op.drop_index(
        "ix_job_description_snapshots_job_opportunity_id",
        table_name="job_description_snapshots",
    )
    op.drop_table("job_description_snapshots")
