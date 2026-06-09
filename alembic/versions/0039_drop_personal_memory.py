"""MEMORY-V3: drop preserved personal_memory chunks.

KNOWLEDGE-CHUNKS preserved ``document_chunks`` rows with
``source_kind='personal_memory'`` (the legacy "save improved answer to my
knowledge base" path). MEMORY-V3 removes that write path entirely — long-term
user state lives in ``memory_ability_states`` now, not the knowledge base — so
the preserved chunks are deleted here. The retriever already excluded them, so
this only reclaims storage; the matching Milvus vectors are swept by the
CLEANUP consistency scan (alembic can't reach Milvus).

Revision ID: 0039_drop_personal_memory
Revises: 0038_conversation_cols
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "0039_drop_personal_memory"
down_revision: Union[str, None] = "0038_conversation_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "document_chunks" in inspect(bind).get_table_names():
        op.execute("DELETE FROM document_chunks WHERE source_kind = 'personal_memory'")


def downgrade() -> None:
    # Irreversible data cleanup — the deleted personal_memory chunks are not
    # restored (the write path that produced them no longer exists).
    pass
