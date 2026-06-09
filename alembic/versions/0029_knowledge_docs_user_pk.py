"""CLEANUP #2 (3/N): knowledge_documents.user_id -> users.id FK.

The knowledge library keys on the stable users.id now; the library API resolves
the caller's username via resolve_user_pk, and ingestion bridges the pk back to
the username for the Milvus / document_chunks index copies (which intentionally
stay username-keyed — they mirror the Milvus metadata scope key).

Clean rebuild: drop the username-keyed ``user_id`` + its two indexes (single +
the ``(user_id, category)`` composite) and re-add as an integer FK to
``users.id`` (no backfill).

Revision ID: 0029_knowledge_docs_user_pk
Revises: 0028_mock_session_user_pk
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0029_knowledge_docs_user_pk"
down_revision: Union[str, None] = "0028_mock_session_user_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "knowledge_documents"
_IDX_SINGLE = "ix_knowledge_documents_user_id"
_IDX_COMPOSITE = "ix_knowledge_docs_user_category"


def _indexes(insp) -> set[str]:
    return {i["name"] for i in insp.get_indexes(_TABLE)}


def _has_column(insp, col: str) -> bool:
    return col in {c["name"] for c in insp.get_columns(_TABLE)}


def _swap_user_id(bind, new_type) -> None:
    insp = inspect(bind)
    idx = _indexes(insp)
    if _IDX_COMPOSITE in idx:
        op.drop_index(_IDX_COMPOSITE, table_name=_TABLE)
    if _IDX_SINGLE in idx:
        op.drop_index(_IDX_SINGLE, table_name=_TABLE)
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
    op.create_index(_IDX_COMPOSITE, _TABLE, ["user_id", "category"])


def upgrade() -> None:
    _swap_user_id(op.get_bind(), "int")


def downgrade() -> None:
    _swap_user_id(op.get_bind(), "str")
