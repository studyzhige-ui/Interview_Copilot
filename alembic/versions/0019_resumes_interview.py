"""RESUME-INTERVIEW: first-class ``resumes`` + ``interview_qa.saved_document_id``.

Adds the personal-resume entity (keyed on stable ``users.id``, optional
``file_assets`` source, partial-unique "one default per active resume") and the
back-reference column on ``interview_qa`` for an improved answer saved to the
knowledge base. The transcript split and the migration of legacy
``KnowledgeDocument(category='简历')`` rows are coordinated with the
knowledge/conversation packages.

Revision ID: 0019_resumes_interview
Revises: 0018_file_assets_outbox
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0019_resumes_interview"
down_revision: Union[str, None] = "0018_file_assets_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, col: str) -> bool:
    return _has_table(insp, table) and col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _has_table(insp, "resumes"):
        op.create_table(
            "resumes",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column("file_asset_id", sa.String(), sa.ForeignKey("file_assets.id"), nullable=True),
            sa.Column("title", sa.String(), nullable=False, server_default="我的简历"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("raw_text_snapshot", sa.Text(), nullable=True),
            sa.Column("structured_json", sa.Text(), nullable=True),
            sa.Column("parse_status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("parse_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "uq_resumes_one_default_per_user", "resumes", ["user_id"], unique=True,
            postgresql_where=sa.text("is_default AND archived_at IS NULL"),
        )
        op.create_index("ix_resumes_user_active", "resumes", ["user_id", "archived_at"])

    if not _has_column(insp, "interview_qa", "saved_document_id"):
        op.add_column("interview_qa", sa.Column("saved_document_id", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _has_column(insp, "interview_qa", "saved_document_id"):
        op.drop_column("interview_qa", "saved_document_id")
    if _has_table(insp, "resumes"):
        op.drop_table("resumes")
