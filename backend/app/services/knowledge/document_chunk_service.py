"""Read/write the ``document_chunks`` Postgres fact table.

This is the project's chunk store — it replaces the LlamaIndex
``PostgresDocumentStore`` for the knowledge base. Ingestion writes chunk rows
here (alongside the Milvus index); full-text reconstruction and the keyword
(BM25) source read from here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk


def _node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if not text and hasattr(node, "get_content"):
        try:
            text = node.get_content()
        except Exception:  # noqa: BLE001
            text = None
    return str(text or "")


def write_chunks(
    db: Session,
    *,
    nodes: list[Any],
    user_id: str,
    source_kind: str,
    document_id: str | None = None,
    metadata: dict | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Persist LlamaIndex ``nodes`` as ``document_chunks`` rows.

    Idempotent per document: when ``document_id`` is set, any existing chunks
    for it are replaced (re-ingest produces a fresh chunk set). Returns the
    chunk + node-id summary the worker stores on the KnowledgeDocument.
    """
    if document_id is not None:
        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id,
        ).delete(synchronize_session=False)

    meta_str = json.dumps(metadata, ensure_ascii=False) if metadata else None
    node_ids: list[str] = []
    for idx, node in enumerate(nodes):
        text = _node_text(node)
        node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
        db.add(
            DocumentChunk(
                document_id=document_id,
                node_id=node_id,
                user_id=user_id,
                source_kind=source_kind,
                chunk_index=idx,
                text=text,
                text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
                metadata_json=meta_str,
            )
        )
        if node_id:
            node_ids.append(str(node_id))
    if commit:
        db.commit()
    return {"chunk_count": len(nodes), "node_ids": node_ids}


def read_document_text(db: Session, document_id: str, *, max_chars: int = 20000) -> tuple[str, int]:
    """Concatenate a document's chunks in order. Returns (text, chunk_count)."""
    rows = (
        db.query(DocumentChunk.text)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not rows:
        return "", 0
    pieces = [r[0] for r in rows if r[0]]
    if not pieces:
        return "", 0
    return "\n\n".join(pieces)[:max_chars], len(pieces)


def delete_document_chunks(db: Session, document_id: str, *, commit: bool = True) -> list[str]:
    """Delete a document's chunks; return their Milvus node_ids for index cleanup."""
    rows = (
        db.query(DocumentChunk.node_id)
        .filter(DocumentChunk.document_id == document_id)
        .all()
    )
    node_ids = [r[0] for r in rows if r[0]]
    db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id,
    ).delete(synchronize_session=False)
    if commit:
        db.commit()
    return node_ids
