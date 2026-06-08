"""CLEANUP #2 (4/N): interview_records.user_id -> users.id FK.

The interview record now keys on the stable users.id. The API + record service
resolve the caller's username via resolve_user_pk; the analysis worker compares
the FileAsset owner pk directly; the dreaming worker bridges the record's pk
back to the username for the (username-keyed) memory dispatch.

Clean rebuild: drop the username-keyed ``user_id`` + its three indexes (single +
two composites) and re-add as an integer FK to ``users.id`` (no backfill).

Revision ID: 0030_interview_records_user_pk
Revises: 0029_knowledge_docs_user_pk
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0030_interview_records_user_pk"
down_revision: Union[str, None] = "0029_knowledge_docs_user_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "interview_records"
_IDX_SINGLE = "ix_interview_records_user_id"
_IDX_CREATED = "ix_interview_records_user_created"
_IDX_DREAMED = "ix_interview_records_user_last_dreamed"


def _indexes(insp) -> set[str]:
    return {i["name"] for i in insp.get_indexes(_TABLE)}


def _has_column(insp, col: str) -> bool:
    return col in {c["name"] for c in insp.get_columns(_TABLE)}


def _swap_user_id(bind, new_type) -> None:
    insp = inspect(bind)
    idx = _indexes(insp)
    for name in (_IDX_CREATED, _IDX_DREAMED, _IDX_SINGLE):
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
    op.create_index(_IDX_CREATED, _TABLE, ["user_id", "created_at"])
    op.create_index(_IDX_DREAMED, _TABLE, ["user_id", "last_dreamed_at"])


def upgrade() -> None:
    _swap_user_id(op.get_bind(), "int")


def downgrade() -> None:
    _swap_user_id(op.get_bind(), "str")
