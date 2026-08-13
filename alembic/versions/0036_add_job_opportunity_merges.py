"""Add reversible duplicate relations for JobOpportunity.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_opportunity_merges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("duplicate_opportunity_id", sa.String(length=35), nullable=False),
        sa.Column("canonical_opportunity_id", sa.String(length=35), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("operation_key", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "confirmation_source_identity", sa.String(length=256), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retraction_operation_key", sa.String(length=200), nullable=True),
        sa.Column("retraction_reason", sa.Text(), nullable=True),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'retracted')",
            name="ck_job_opportunity_merges_status",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_job_opportunity_merges_version_positive",
        ),
        sa.CheckConstraint(
            "duplicate_opportunity_id <> canonical_opportunity_id",
            name="ck_job_opportunity_merges_distinct",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["duplicate_opportunity_id"],
            ["job_opportunities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_opportunity_id"],
            ["job_opportunities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "operation_key",
            name="uq_job_opportunity_merges_user_operation",
        ),
        sa.UniqueConstraint(
            "user_id",
            "retraction_operation_key",
            name="uq_job_opportunity_merges_user_retraction",
        ),
    )
    op.create_index(
        op.f("ix_job_opportunity_merges_user_id"),
        "job_opportunity_merges",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_opportunity_merges_user_status",
        "job_opportunity_merges",
        ["user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_job_opportunity_merges_active_duplicate",
        "job_opportunity_merges",
        ["duplicate_opportunity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_job_opportunity_merges_active_duplicate",
        table_name="job_opportunity_merges",
    )
    op.drop_index(
        "ix_job_opportunity_merges_user_status",
        table_name="job_opportunity_merges",
    )
    op.drop_index(
        op.f("ix_job_opportunity_merges_user_id"),
        table_name="job_opportunity_merges",
    )
    op.drop_table("job_opportunity_merges")
