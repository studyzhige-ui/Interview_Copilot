"""CLEANUP #2 (6/N): document_chunks.user_id -> users.id FK.

The RAG retrieval scope key moves from the username string to the stable
users.id, end-to-end: ingestion writes the pk to both the Milvus node metadata
and this column; retrieval (vector + BM25) filters both by the pk. document_chunks
is the Postgres fact source for knowledge + personal_memory chunks.

Clean rebuild: drop the username-keyed ``user_id`` + its two indexes
(``ix_document_chunks_user_source`` composite + the single index) and re-add as an
integer FK to ``users.id`` (no backfill). ``ix_document_chunks_doc_order``
(document_id, chunk_index) does not reference user_id and is untouched.

NOTE (operator): the Milvus RAG collection (``interview_copilot_rag``) stores the
username as each node's ``user_id`` metadata for chunks ingested before this
change. After deploying, those vectors no longer match the new pk scope filter —
reingest the affected users (or drop + rebuild the collection) so retrieval sees
them. In a fresh environment the collection is created with pk metadata on first
ingest, so no action is needed.

Revision ID: 0032_document_chunks_user_pk
Revises: 0031_chat_sessions_user_pk
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0032_document_chunks_user_pk"
down_revision: Union[str, None] = "0031_chat_sessions_user_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "document_chunks"
_IDX_SINGLE = "ix_document_chunks_user_id"
_IDX_USER_SOURCE = "ix_document_chunks_user_source"


def _indexes(insp) -> set[str]:
    return {i["name"] for i in insp.get_indexes(_TABLE)}


def _has_column(insp, col: str) -> bool:
    return col in {c["name"] for c in insp.get_columns(_TABLE)}


def _swap_user_id(bind, new_type) -> None:
    insp = inspect(bind)
    idx = _indexes(insp)
    for name in (_IDX_USER_SOURCE, _IDX_SINGLE):
        if name in idx:
            op.drop_index(name, table_name=_TABLE)
    if _has_column(insp, "user_id"):
        op.drop_column(_TABLE, "user_id")
    if new_type == "int":
        op.add_column(
            _TABLE,
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
            ),
        )
    else:
        op.add_column(_TABLE, sa.Column("user_id", sa.String(), nullable=False))
    op.create_index(_IDX_SINGLE, _TABLE, ["user_id"])
    op.create_index(_IDX_USER_SOURCE, _TABLE, ["user_id", "source_kind"])


def upgrade() -> None:
    _swap_user_id(op.get_bind(), "int")


def downgrade() -> None:
    _swap_user_id(op.get_bind(), "str")
