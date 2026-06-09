"""MODEL-CONFIG: user_model_credentials validation-status columns (RFC §5.2).

Adds ``status`` (default 'active'), ``last_validated_at``, ``last_validation_error``.
(``deleted_at`` is intentionally omitted — credentials hard-delete for security;
soft-deleting an encrypted secret is an anti-pattern.)

Revision ID: 0036_credential_validation
Revises: 0035_knowledge_chunks_columns
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0036_credential_validation"
down_revision: Union[str, None] = "0035_knowledge_chunks_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "user_model_credentials"
_ADD = [
    ("status", lambda: sa.Column("status", sa.String(length=16), nullable=False, server_default="active")),
    ("last_validated_at", lambda: sa.Column("last_validated_at", sa.DateTime(), nullable=True)),
    ("last_validation_error", lambda: sa.Column("last_validation_error", sa.Text(), nullable=True)),
]


def _cols(insp) -> set[str]:
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    have = _cols(inspect(op.get_bind()))
    for name, factory in _ADD:
        if name not in have:
            op.add_column(_TABLE, factory())


def downgrade() -> None:
    have = _cols(inspect(op.get_bind()))
    for name, _ in reversed(_ADD):
        if name in have:
            op.drop_column(_TABLE, name)
