"""CLEANUP #2: mock_interview_runtime.user_id -> users.id FK.

First table of the username->stable-id migration. ``mock_interview_runtime`` is
reached only through ``mock_runtime_service`` (which now resolves the caller's
username via ``resolve_user_pk``), so the boundary is self-contained.

Clean rebuild: the username-keyed ``user_id`` column + its indexes are dropped
and re-added as an integer FK to ``users.id`` (no data backfill).

Revision ID: 0027_mock_runtime_user_pk
Revises: 0026_source_type_to_source_kind
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0027_mock_runtime_user_pk"
down_revision: Union[str, None] = "0026_source_type_to_source_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "mock_interview_runtime"


def _indexes(insp) -> set[str]:
    return {i["name"] for i in insp.get_indexes(_TABLE)}


def _columns(insp) -> set[str]:
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    idx = _indexes(insp)
    if "ix_mock_runtime_user_status" in idx:
        op.drop_index("ix_mock_runtime_user_status", table_name=_TABLE)
    if "ix_mock_interview_runtime_user_id" in idx:
        op.drop_index("ix_mock_interview_runtime_user_id", table_name=_TABLE)
    if "user_id" in _columns(insp):
        op.drop_column(_TABLE, "user_id")
    op.add_column(
        _TABLE,
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
    )
    op.create_index("ix_mock_interview_runtime_user_id", _TABLE, ["user_id"])
    op.create_index("ix_mock_runtime_user_status", _TABLE, ["user_id", "status"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    idx = _indexes(insp)
    if "ix_mock_runtime_user_status" in idx:
        op.drop_index("ix_mock_runtime_user_status", table_name=_TABLE)
    if "ix_mock_interview_runtime_user_id" in idx:
        op.drop_index("ix_mock_interview_runtime_user_id", table_name=_TABLE)
    if "user_id" in _columns(insp):
        op.drop_column(_TABLE, "user_id")
    op.add_column(_TABLE, sa.Column("user_id", sa.String(), nullable=False))
    op.create_index("ix_mock_interview_runtime_user_id", _TABLE, ["user_id"])
    op.create_index("ix_mock_runtime_user_status", _TABLE, ["user_id", "status"])
