"""CLEANUP: drop the dead ``knowledge_documents.node_ids`` column.

``node_ids`` was a write-only JSON column — the worker wrote it after ingest but
nothing ever read it. Milvus node ids are sourced from ``document_chunks.node_id``
(the fact source) for index cleanup since KNOWLEDGE-CHUNKS. ``ref_doc_ids`` is
left intact (still read).

Revision ID: 0024_drop_kdoc_node_ids
Revises: 0023_drop_old_memory
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0024_drop_kdoc_node_ids"
down_revision: Union[str, None] = "0023_drop_old_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, col: str) -> bool:
    if table not in insp.get_table_names():
        return False
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = inspect(op.get_bind())
    if _has_column(insp, "knowledge_documents", "node_ids"):
        op.drop_column("knowledge_documents", "node_ids")


def downgrade() -> None:
    insp = inspect(op.get_bind())
    if not _has_column(insp, "knowledge_documents", "node_ids"):
        op.add_column(
            "knowledge_documents",
            sa.Column("node_ids", sa.Text(), nullable=False, server_default="[]"),
        )
