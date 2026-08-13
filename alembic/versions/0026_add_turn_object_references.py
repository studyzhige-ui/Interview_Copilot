"""Add durable typed product-object identities to ordinary Turn ingress.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _empty_jsonb() -> sa.Column:
    return sa.Column(
        "object_references_json",
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )


def upgrade() -> None:
    op.add_column("pending_submissions", _empty_jsonb())
    op.add_column("conversation_turns", _empty_jsonb())
    op.alter_column("pending_submissions", "object_references_json", server_default=None)
    op.alter_column("conversation_turns", "object_references_json", server_default=None)


def downgrade() -> None:
    op.drop_column("conversation_turns", "object_references_json")
    op.drop_column("pending_submissions", "object_references_json")
