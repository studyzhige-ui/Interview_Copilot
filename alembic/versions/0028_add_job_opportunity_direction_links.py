"""Relate JobOpportunity projections to owned CareerProfile directions.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_opportunities",
        sa.Column(
            "direction_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_job_opportunities_direction_version",
        "job_opportunities",
        "direction_version >= 0",
    )
    op.create_table(
        "job_opportunity_direction_links",
        sa.Column("id", sa.String(length=37), nullable=False),
        sa.Column("job_opportunity_id", sa.String(length=35), nullable=False),
        sa.Column(
            "career_profile_direction_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_identity", sa.String(length=256), nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('user_assertion', 'observation', "
            "'tool_result', 'provider_receipt')",
            name="ck_job_opportunity_direction_links_source_kind",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_job_opportunity_direction_links_position",
        ),
        sa.ForeignKeyConstraint(
            ["career_profile_direction_id"],
            ["career_profile_directions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_opportunity_id"],
            ["job_opportunities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_opportunity_id",
            "career_profile_direction_id",
            name="uq_job_opportunity_direction_links_pair",
        ),
        sa.UniqueConstraint(
            "job_opportunity_id",
            "position",
            name="uq_job_opportunity_direction_links_position",
        ),
    )
    op.create_index(
        op.f("ix_job_opportunity_direction_links_job_opportunity_id"),
        "job_opportunity_direction_links",
        ["job_opportunity_id"],
        unique=False,
    )
    op.create_index(
        "ix_job_opportunity_direction_links_direction",
        "job_opportunity_direction_links",
        ["career_profile_direction_id", "job_opportunity_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_opportunity_direction_links_direction",
        table_name="job_opportunity_direction_links",
    )
    op.drop_index(
        op.f("ix_job_opportunity_direction_links_job_opportunity_id"),
        table_name="job_opportunity_direction_links",
    )
    op.drop_table("job_opportunity_direction_links")
    op.drop_constraint(
        "ck_job_opportunities_direction_version",
        "job_opportunities",
        type_="check",
    )
    op.drop_column("job_opportunities", "direction_version")
