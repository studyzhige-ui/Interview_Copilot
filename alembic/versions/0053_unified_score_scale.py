"""Identify legacy stored score units; new scores use the shared ten-point scale.

Revision ID: 0053
Revises: 0052
"""

from alembic import op
import sqlalchemy as sa

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ability_signals",
        sa.Column("score_scale_version", sa.String(40), nullable=True),
    )
    # Do not divide existing numbers in-place: raw history remains auditable.
    op.execute(
        sa.text(
            "UPDATE ability_signals SET score_scale_version = 'score100-legacy-v2' WHERE rubric_version = 'evidence-v2'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE ability_signals SET score_scale_version = 'score10-v1' WHERE rubric_version LIKE 'interview_analysis_v%'"
        )
    )
    # Other historical rubrics have unknown units. They remain readable but are
    # not silently admitted into a numeric trend. Reassessment can replace them.


def downgrade():
    new_units = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM ability_signals WHERE score_scale_version IS NOT NULL "
            "AND COALESCE(rubric_version, '') <> 'evidence-v2' "
            "AND COALESCE(rubric_version, '') NOT LIKE 'interview_analysis_v%'"
        )
    )
    if new_units:
        raise RuntimeError("score_provenance_requires_export_before_rollback")
    op.drop_column("ability_signals", "score_scale_version")
