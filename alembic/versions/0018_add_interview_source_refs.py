"""Add explicit InterviewRecord-scoped attachment sources.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_source_refs",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("interview_record_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("file_asset_id", sa.String(), nullable=False),
        sa.Column("source_document_id", sa.String(), nullable=False),
        sa.Column("file_asset_version", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("origin_conversation_id", sa.String(length=128), nullable=False),
        sa.Column("origin_attachment_ref_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["interview_record_id"],
            ["interview_records.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["file_asset_id"],
            ["file_assets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "interview_record_id",
            "file_asset_id",
            "file_asset_version",
            name="uq_interview_source_refs_record_asset_version",
        ),
    )
    op.create_index(
        "ix_interview_source_refs_interview_record_id",
        "interview_source_refs",
        ["interview_record_id"],
    )
    op.create_index(
        "ix_interview_source_refs_user_id",
        "interview_source_refs",
        ["user_id"],
    )
    op.create_index(
        "ix_interview_source_refs_file_asset_id",
        "interview_source_refs",
        ["file_asset_id"],
    )
    op.create_index(
        "ix_interview_source_refs_source_document_id",
        "interview_source_refs",
        ["source_document_id"],
    )
    op.create_index(
        "ix_interview_source_refs_record_removed",
        "interview_source_refs",
        ["interview_record_id", "removed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_source_refs_record_removed",
        table_name="interview_source_refs",
    )
    op.drop_index(
        "ix_interview_source_refs_source_document_id",
        table_name="interview_source_refs",
    )
    op.drop_index(
        "ix_interview_source_refs_file_asset_id",
        table_name="interview_source_refs",
    )
    op.drop_index(
        "ix_interview_source_refs_user_id",
        table_name="interview_source_refs",
    )
    op.drop_index(
        "ix_interview_source_refs_interview_record_id",
        table_name="interview_source_refs",
    )
    op.drop_table("interview_source_refs")
