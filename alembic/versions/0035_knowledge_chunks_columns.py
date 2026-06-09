"""KNOWLEDGE-CHUNKS: knowledge_documents + document_chunks column widening.

Clean rebuild (no backfill).

  * knowledge_documents: upload_id -> file_asset_id (+ nullable, for fileless
    improved_qa / manual_text docs); storage_uri / object_key relaxed to
    nullable; add source_ref_type / source_ref_id / source_interview_record_id /
    content_text / deleted_at.
  * document_chunks: add index_status / lexical_index_id / deleted_at
    (text_hash already exists).

Revision ID: 0035_knowledge_chunks_columns
Revises: 0034_resume_interview_split
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0035_knowledge_chunks_columns"
down_revision: Union[str, None] = "0034_resume_interview_split"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KD = "knowledge_documents"
_DC = "document_chunks"


def _cols(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def _indexes(insp, table: str) -> set[str]:
    return {i["name"] for i in insp.get_indexes(table)}


_KD_ADD = [
    ("source_ref_type", lambda: sa.Column("source_ref_type", sa.String(), nullable=True)),
    ("source_ref_id", lambda: sa.Column("source_ref_id", sa.String(), nullable=True)),
    ("source_interview_record_id", lambda: sa.Column("source_interview_record_id", sa.String(), nullable=True)),
    ("content_text", lambda: sa.Column("content_text", sa.Text(), nullable=True)),
    ("deleted_at", lambda: sa.Column("deleted_at", sa.DateTime(), nullable=True)),
]
_DC_ADD = [
    ("index_status", lambda: sa.Column("index_status", sa.String(), nullable=False, server_default="pending")),
    ("lexical_index_id", lambda: sa.Column("lexical_index_id", sa.String(), nullable=True)),
    ("deleted_at", lambda: sa.Column("deleted_at", sa.DateTime(), nullable=True)),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    # ── knowledge_documents ──────────────────────────────────────────────
    kd_cols = _cols(insp, _KD)
    if "upload_id" in kd_cols and "file_asset_id" not in kd_cols:
        op.alter_column(_KD, "upload_id", new_column_name="file_asset_id",
                        existing_type=sa.String(), nullable=True)
        if not is_sqlite:
            op.execute(
                "ALTER INDEX IF EXISTS ix_knowledge_documents_upload_id "
                "RENAME TO ix_knowledge_documents_file_asset_id"
            )
    elif "file_asset_id" not in kd_cols:
        op.add_column(_KD, sa.Column("file_asset_id", sa.String(), nullable=True))

    # storage_uri / object_key -> nullable (fileless docs).
    op.alter_column(_KD, "storage_uri", existing_type=sa.String(), nullable=True)
    op.alter_column(_KD, "object_key", existing_type=sa.String(), nullable=True)

    have = _cols(inspect(bind), _KD)
    for name, factory in _KD_ADD:
        if name not in have:
            op.add_column(_KD, factory())
    kd_idx = _indexes(inspect(bind), _KD)
    if "ix_knowledge_documents_source_ref_id" not in kd_idx:
        op.create_index("ix_knowledge_documents_source_ref_id", _KD, ["source_ref_id"])
    if "ix_knowledge_documents_source_interview_record_id" not in kd_idx:
        op.create_index(
            "ix_knowledge_documents_source_interview_record_id", _KD,
            ["source_interview_record_id"],
        )

    # ── document_chunks ──────────────────────────────────────────────────
    dc_cols = _cols(inspect(bind), _DC)
    for name, factory in _DC_ADD:
        if name not in dc_cols:
            op.add_column(_DC, factory())


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    dc_cols = _cols(inspect(bind), _DC)
    for name, _ in _DC_ADD:
        if name in dc_cols:
            op.drop_column(_DC, name)

    kd_idx = _indexes(inspect(bind), _KD)
    for idx in (
        "ix_knowledge_documents_source_ref_id",
        "ix_knowledge_documents_source_interview_record_id",
    ):
        if idx in kd_idx:
            op.drop_index(idx, table_name=_KD)
    have = _cols(inspect(bind), _KD)
    for name, _ in _KD_ADD:
        if name in have:
            op.drop_column(_KD, name)

    op.alter_column(_KD, "object_key", existing_type=sa.String(), nullable=False)
    op.alter_column(_KD, "storage_uri", existing_type=sa.String(), nullable=False)
    have = _cols(inspect(bind), _KD)
    if "file_asset_id" in have and "upload_id" not in have:
        if not is_sqlite:
            op.execute(
                "ALTER INDEX IF EXISTS ix_knowledge_documents_file_asset_id "
                "RENAME TO ix_knowledge_documents_upload_id"
            )
        op.alter_column(_KD, "file_asset_id", new_column_name="upload_id",
                        existing_type=sa.String(), nullable=False)
