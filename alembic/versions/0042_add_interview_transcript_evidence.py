"""Add auditable word evidence and QA provenance.

Revision ID: 0042
Revises: 0041
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interview_transcripts",
        sa.Column("evidence_schema_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "interview_transcripts",
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "interview_transcripts",
        sa.Column("structure_schema_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "interview_transcripts",
        sa.Column(
            "structure_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "interview_transcripts",
        sa.Column(
            "quality_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_interview_transcripts_evidence_schema",
        "interview_transcripts",
        "evidence_schema_version IS NULL OR evidence_schema_version >= 2",
    )
    op.create_check_constraint(
        "ck_interview_transcripts_structure_schema",
        "interview_transcripts",
        "structure_schema_version IS NULL OR structure_schema_version >= 1",
    )

    op.add_column(
        "interview_qa",
        sa.Column("source_transcript_id", sa.String(), nullable=True),
    )
    op.add_column(
        "interview_qa",
        sa.Column(
            "source_provenance_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_interview_qa_source_transcript",
        "interview_qa",
        "interview_transcripts",
        ["source_transcript_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_interview_qa_source_transcript_id",
        "interview_qa",
        ["source_transcript_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_interview_qa_source_transcript_id", table_name="interview_qa")
    op.drop_constraint(
        "fk_interview_qa_source_transcript", "interview_qa", type_="foreignkey"
    )
    op.drop_column("interview_qa", "source_provenance_json")
    op.drop_column("interview_qa", "source_transcript_id")

    op.drop_constraint(
        "ck_interview_transcripts_structure_schema",
        "interview_transcripts",
        type_="check",
    )
    op.drop_constraint(
        "ck_interview_transcripts_evidence_schema",
        "interview_transcripts",
        type_="check",
    )
    op.drop_column("interview_transcripts", "quality_json")
    op.drop_column("interview_transcripts", "structure_json")
    op.drop_column("interview_transcripts", "structure_schema_version")
    op.drop_column("interview_transcripts", "evidence_json")
    op.drop_column("interview_transcripts", "evidence_schema_version")
