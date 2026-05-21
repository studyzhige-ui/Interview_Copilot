"""Drop the legacy memory_items table (v3 cleanup).

The v2 multi-row memory_items table is retired in favour of:
  * users.user_profile_doc — single markdown doc per user
  * knowledge_docs / strategy_docs / habit_docs — v3 typed memory

Operators MUST run scripts/migrate_memory_to_v3.py to distil any
existing interview_fact rows into knowledge_docs BEFORE applying this
revision. The dry-run mode of that script reports what would be
migrated; the --commit mode does the actual writes.

Once the table is dropped, the data is gone. The Milvus collection
named by ``MEMORY_MILVUS_COLLECTION`` is also no longer used — drop
it manually on the Milvus side if disk space matters.

Revision ID: 0003_drop_memory_items
Revises: 0002_memory_v3
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003_drop_memory_items"
down_revision: Union[str, None] = "0002_memory_v3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop indexes explicitly so downgrade can recreate them by name.
    # Use IF EXISTS-style helpers via inspector to be tolerant of dbs
    # where some indexes were never created (e.g. minimal test setups).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {
        idx["name"] for idx in inspector.get_indexes("memory_items")
    } if inspector.has_table("memory_items") else set()

    for idx_name in (
        "ix_memory_items_id",
        "ix_memory_items_user_id",
        "ix_memory_items_type",
        "ix_memory_items_scope",
        "ix_memory_items_normalized_key",
    ):
        if idx_name in existing_indexes:
            op.drop_index(idx_name, table_name="memory_items")

    if inspector.has_table("memory_items"):
        op.drop_table("memory_items")


def downgrade() -> None:
    # Re-create the v2 schema. Data won't come back — this is just to
    # let an operator roll back the structural change. The fields and
    # types here mirror the original 0001_baseline definition.
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False, server_default="user"),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("normalized_key", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0"),
        sa.Column("importance", sa.Float(), server_default="0.5"),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("last_evidence_seq", sa.Integer(), nullable=True),
        sa.Column("recall_count", sa.Integer(), server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "embedding_status", sa.String(), nullable=False,
            server_default="pending",
        ),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("embedded_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_memory_items_id", "memory_items", ["id"])
    op.create_index("ix_memory_items_user_id", "memory_items", ["user_id"])
    op.create_index("ix_memory_items_type", "memory_items", ["type"])
    op.create_index("ix_memory_items_scope", "memory_items", ["scope"])
    op.create_index(
        "ix_memory_items_normalized_key", "memory_items", ["normalized_key"],
    )
