"""Add page/token provenance columns to ``document_chunks``.

Phase B (RAG ingestion optimization, §4.4.4): the chunk fact table gains
``page_start`` / ``page_end`` (best-effort page provenance from the parser
page_map) and ``token_count`` (real embedding-tokenizer count for chunk-size
/ oversize observability). All three are nullable — page-less formats and
not-yet-recomputed chunks stay NULL.

Revision ID: 0041_document_chunk_provenance
Revises: 0040_drop_mock_sessions
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0041_document_chunk_provenance"
down_revision: Union[str, None] = "0040_drop_mock_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = ("page_start", "page_end", "token_count")


def upgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in inspect(bind).get_columns("document_chunks")}
    for name in _NEW_COLUMNS:
        if name not in existing:
            op.add_column(
                "document_chunks", sa.Column(name, sa.Integer(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing = {c["name"] for c in inspect(bind).get_columns("document_chunks")}
    targets = [name for name in _NEW_COLUMNS if name in existing]
    if not targets:
        return
    # SQLite needs batch mode to drop columns (no native DROP COLUMN pre-3.35).
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("document_chunks") as batch:
            for name in targets:
                batch.drop_column(name)
    else:
        for name in targets:
            op.drop_column("document_chunks", name)
