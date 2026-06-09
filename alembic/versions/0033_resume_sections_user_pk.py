"""CLEANUP #2 (7/N): resume_sections.user_id -> users.id FK.

The final username-keyed table. Like document_chunks, resume_sections is a
retrieval-scope mirror: its ``user_id`` is the scope key written to the resume
Milvus collection's node metadata. This moves that key from the username string
to the stable users.id, end-to-end — resume_service resolves username->pk at its
boundary (persist + the get_sections reads), and resume_vector_service filters
the Milvus collection by the pk.

Clean rebuild: drop the username-keyed ``user_id`` + its single index and re-add
as an integer FK to ``users.id`` (no backfill). The upload_id / section_type
indexes do not reference user_id and are untouched.

NOTE (operator): the resume Milvus collection (``interview_copilot_resume``)
stores the username as each node's ``user_id`` metadata for sections embedded
before this change. After deploying, reingest (backfill_pending re-embeds from
the Postgres fact rows) or drop + rebuild the collection so retrieval matches the
pk scope filter. In a fresh environment the collection is created with pk metadata
on first embed, so no action is needed.

Revision ID: 0033_resume_sections_user_pk
Revises: 0032_document_chunks_user_pk
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0033_resume_sections_user_pk"
down_revision: Union[str, None] = "0032_document_chunks_user_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "resume_sections"
_IDX_SINGLE = "ix_resume_sections_user_id"


def _indexes(insp) -> set[str]:
    return {i["name"] for i in insp.get_indexes(_TABLE)}


def _has_column(insp, col: str) -> bool:
    return col in {c["name"] for c in insp.get_columns(_TABLE)}


def _swap_user_id(bind, new_type) -> None:
    insp = inspect(bind)
    if _IDX_SINGLE in _indexes(insp):
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


def upgrade() -> None:
    _swap_user_id(op.get_bind(), "int")


def downgrade() -> None:
    _swap_user_id(op.get_bind(), "str")
