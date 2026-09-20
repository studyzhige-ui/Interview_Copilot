"""Prepare embeddings outside transactions; publish canonical snapshots once."""

from __future__ import annotations

from typing import Any
from dataclasses import dataclass

from app.db import database
from app.models.knowledge import KnowledgeDocument
from app.rag import hybrid_index
from app.rag.index.source import source_snapshot, SourceSnapshot
from app.rag.ingest.embedding import (
    build_retrieval_passages,
    embed_passages,
    node_id,
    node_text,
)


def replace_document_rows(
    nodes: list[Any],
    passages: list[str],
    vectors: list[list[float]],
    *,
    user_id: int,
    source_kind: str,
    document_id: str,
    expected_source: SourceSnapshot | None = None,
    embedding_profile: dict | None = None,
) -> None:
    if not len(nodes) == len(passages) == len(vectors):
        raise ValueError(
            "every canonical chunk requires exactly one passage and vector"
        )
    rows = [
        dict(id=node_id(node), source_text=node_text(node), text=passage, dense=vector)
        for node, passage, vector in zip(nodes, passages, vectors, strict=True)
    ]
    hybrid_index.replace_document(
        user_pk=user_id,
        document_id=document_id,
        source_kind=source_kind,
        rows=rows,
        expected_source=expected_source,
        embedding_profile=embedding_profile,
    )


@dataclass(frozen=True)
class _ChunkSnapshot:
    node_id: str
    text: str
    metadata_json: str | None


def reindex_document(document_id: str, *, embed_model: Any | None = None) -> int:
    """Rebuild from current canonical facts, never from an old vector index.

    This operation owns its short Sessions. Callers must not hold a business
    transaction/row lock while waiting for it. Source edits and deletions during
    model execution are caught before any projection is committed.
    """
    from app.rag.document_chunk_service import read_indexable_chunks
    from app.usage.runtime import for_owner

    with database.SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if document is None or document.deleted_at is not None:
            # Deletion owns projection cleanup via FK/outbox. A late upsert
            # cannot resurrect a deleted document.
            return 0
        snapshot = source_snapshot(db, document)
        if document.source_kind == "chat_attachment" or document.conversation_id:
            raise PermissionError(
                "private conversation sources cannot be globally indexed"
            )
        chunks = read_indexable_chunks(db, document_id)
        if any(
            c.user_id != snapshot.user_id or c.source_kind != snapshot.source_kind
            for c in chunks
        ):
            raise PermissionError("canonical chunk ownership/type mismatch")
        nodes = [_ChunkSnapshot(c.node_id, c.text, c.metadata_json) for c in chunks]
    if not nodes:
        raise ValueError(
            "canonical_chunks_missing: reparse the source before reindexing"
        )
    passages = build_retrieval_passages(nodes, document_title=snapshot.title)
    with for_owner(snapshot.user_id, operation=f"reindex:{document_id}"):
        batch = embed_passages(passages, embed_model=embed_model)
    vectors, profile = batch.vectors, batch.profile
    replace_document_rows(
        nodes,
        passages,
        vectors,
        user_id=snapshot.user_id,
        source_kind=snapshot.source_kind,
        document_id=document_id,
        expected_source=snapshot,
        embedding_profile=profile,
    )
    return len(nodes)


__all__ = ["reindex_document", "replace_document_rows"]
