"""CLEANUP #1: retire the direct-upload path — drop user_uploads.

All three upload routes (knowledge / interview-audio / resume) now write
``file_assets`` via ``file_asset_service`` instead of the old ``user_uploads``
table via ``upload_service``. This repoints the one remaining FK
(``knowledge_documents.upload_id`` → ``file_assets.id``) and drops the now-unused
``user_uploads`` table. The interview_records ``*_upload_id`` columns are plain
String (no FK) and now simply hold file_asset ids; ``resume`` already keyed on
``file_assets``.

Clean rebuild: no data backfill.

Revision ID: 0025_uploads_to_file_assets
Revises: 0024_drop_kdoc_node_ids
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0025_uploads_to_file_assets"
down_revision: Union[str, None] = "0024_drop_kdoc_node_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_FK = "fk_knowledge_documents_upload_file_asset"


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    fks = insp.get_foreign_keys("knowledge_documents")
    # Drop the old FK that points at user_uploads (auto-named by Postgres).
    for fk in fks:
        if fk.get("referred_table") == "user_uploads" and fk.get("name"):
            op.drop_constraint(fk["name"], "knowledge_documents", type_="foreignkey")
    # Add the FK to file_assets (skip if a file_assets FK already exists).
    referred = {fk.get("referred_table") for fk in fks}
    names = {fk.get("name") for fk in fks}
    if "file_assets" not in referred and _NEW_FK not in names:
        op.create_foreign_key(
            _NEW_FK, "knowledge_documents", "file_assets", ["upload_id"], ["id"],
        )

    if _has_table(insp, "user_uploads"):
        op.drop_table("user_uploads")


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _has_table(insp, "user_uploads"):
        op.create_table(
            "user_uploads",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("original_filename", sa.String(), nullable=False),
            sa.Column("storage_uri", sa.String(), nullable=False),
            sa.Column("object_key", sa.String(), nullable=False, unique=True),
            sa.Column("content_type", sa.String(), nullable=True),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending_upload"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_user_uploads_user_id", "user_uploads", ["user_id"])
        op.create_index("ix_user_uploads_purpose", "user_uploads", ["purpose"])
        op.create_index("ix_user_uploads_object_key", "user_uploads", ["object_key"], unique=True)
        op.create_index("ix_user_uploads_status", "user_uploads", ["status"])
        op.create_index("ix_user_uploads_user_purpose", "user_uploads", ["user_id", "purpose"])

    fks = insp.get_foreign_keys("knowledge_documents")
    for fk in fks:
        if fk.get("referred_table") == "file_assets" and fk.get("name"):
            op.drop_constraint(fk["name"], "knowledge_documents", type_="foreignkey")
    referred = {fk.get("referred_table") for fk in fks}
    if "user_uploads" not in referred:
        op.create_foreign_key(
            "knowledge_documents_upload_id_fkey",
            "knowledge_documents", "user_uploads", ["upload_id"], ["id"],
        )
