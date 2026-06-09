"""KNOWLEDGE-CHUNKS: add ``document_chunks`` (Postgres chunk fact source).

Postgres owns chunk text (this table), Milvus owns the retrieval index. Replaces
the LlamaIndex ``PostgresDocumentStore`` as the knowledge-base chunk store:
full-text reconstruction + the keyword (BM25) source read from here. A row with
NULL ``document_id`` is a ``personal_memory`` chunk (no knowledge_documents row).

Revision ID: 0020_document_chunks
Revises: 0019_resumes_interview
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0020_document_chunks"
down_revision: Union[str, None] = "0019_resumes_interview"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _has_table(insp, "document_chunks"):
        return
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "document_id", sa.String(),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=True, index=True,
        ),
        sa.Column("node_id", sa.String(), nullable=True, index=True),
        sa.Column("user_id", sa.String(), nullable=False, index=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_document_chunks_user_source", "document_chunks", ["user_id", "source_type"])
    op.create_index("ix_document_chunks_doc_order", "document_chunks", ["document_id", "chunk_index"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _has_table(insp, "document_chunks"):
        op.drop_table("document_chunks")
