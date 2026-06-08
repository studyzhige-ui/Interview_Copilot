"""CLEANUP #4: rename source_type -> source_kind.

Renames the ``source_type`` column to ``source_kind`` on ``knowledge_documents``
and ``document_chunks`` (and the auto-named single-column index on
knowledge_documents). The denormalised value vocabulary is unchanged by this
migration — this is a field rename; the Milvus metadata key is renamed in the
ingestion/retrieval code (clean rebuild re-indexes).

Revision ID: 0026_source_type_to_source_kind
Revises: 0025_uploads_to_file_assets
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "0026_source_type_to_source_kind"
down_revision: Union[str, None] = "0025_uploads_to_file_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, col: str) -> bool:
    return table in insp.get_table_names() and col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _has_column(insp, "knowledge_documents", "source_type"):
        op.alter_column("knowledge_documents", "source_type", new_column_name="source_kind")
    if _has_column(insp, "document_chunks", "source_type"):
        op.alter_column("document_chunks", "source_type", new_column_name="source_kind")
    # The single-col index on knowledge_documents was auto-named after the old
    # column; re-inspect (post-rename) and rename it to match the model.
    names = {i["name"] for i in inspect(bind).get_indexes("knowledge_documents")}
    if (
        "ix_knowledge_documents_source_type" in names
        and "ix_knowledge_documents_source_kind" not in names
    ):
        op.execute(
            "ALTER INDEX ix_knowledge_documents_source_type "
            "RENAME TO ix_knowledge_documents_source_kind"
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    names = {i["name"] for i in insp.get_indexes("knowledge_documents")}
    if (
        "ix_knowledge_documents_source_kind" in names
        and "ix_knowledge_documents_source_type" not in names
    ):
        op.execute(
            "ALTER INDEX ix_knowledge_documents_source_kind "
            "RENAME TO ix_knowledge_documents_source_type"
        )
    if _has_column(insp, "knowledge_documents", "source_kind"):
        op.alter_column("knowledge_documents", "source_kind", new_column_name="source_type")
    if _has_column(insp, "document_chunks", "source_kind"):
        op.alter_column("document_chunks", "source_kind", new_column_name="source_type")
