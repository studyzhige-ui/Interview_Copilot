"""Read/write the ``document_chunks`` Postgres fact table.

This is the project's chunk store — it replaced the LlamaIndex
``PostgresDocumentStore`` for the knowledge base. Ingestion writes chunk rows
here; full-text reconstruction reads from here. The rebuildable pgvector/BM25
projection lives in retrieval_entries in this same PostgreSQL database.
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


# Diagnostic / provenance fields lifted off node.metadata into the chunk's
# metadata_json. Category lives on knowledge_documents and is hydrated there. Warnings
# are not a top-level key — they live inside their owning profile dict
# (cleaning_profile.warnings / parser_profile.warnings / splitter_profile).
# parser_id / parser_profile / ocr_used are produced by the parse stage (E1).
_METADATA_JSON_KEYS = (
    "section_title",
    "heading_path",
    "chunk_type",
    "splitter_id",
    "splitter_profile",
    "parser_id",
    "parser_profile",
    "ocr_used",
    "cleaning_profile",
    "embedding_profile",
)


def _chunk_metadata_json(node_meta: dict) -> str | None:
    """Build a chunk's ``metadata_json`` from the diagnostic keys present on
    its node — per chunk, not a blanket dict. Returns None when nothing
    diagnostic is present (keeps the column NULL rather than ``{}``)."""
    payload = {
        k: node_meta[k] for k in _METADATA_JSON_KEYS if node_meta.get(k) is not None
    }
    return json.dumps(payload, ensure_ascii=False) if payload else None


def write_chunks(
    db: Session,
    *,
    nodes: list[Any],
    user_id: int,
    source_kind: str,
    document_id: str,
    index_status: str = "pending",
    commit: bool = True,
    source_snapshot=None,
) -> dict[str, Any]:
    """Persist LlamaIndex ``nodes`` as ``document_chunks`` rows.

    Idempotent per document: existing chunks are replaced, so re-ingest produces
    one fresh chunk set. Per-chunk
    provenance (page/token columns + diagnostic metadata_json) is lifted off
    each node's metadata, stamped by the parser / cleaning / chunking stages.
    Returns the chunk + node-id summary the worker stores on the document.

    Facts are written ``pending`` by default in a two-phase write: the
    caller persists recoverable pending facts, then atomically replaces the
    retrieval projection and publishes its generation. A failed publication
    retains pending facts and a durable outbox retry.
    """
    from app.models.knowledge import KnowledgeDocument
    from app.rag.index.source import IndexSourceChanged, source_snapshot as snapshot_of

    document = (
        db.query(KnowledgeDocument).filter_by(id=document_id).with_for_update().first()
    )
    if document is None:
        raise IndexSourceChanged("canonical document no longer exists")
    if document.user_id != user_id or document.source_kind != source_kind:
        raise PermissionError("canonical document owner/source mismatch")
    current = snapshot_of(db, document)
    if source_snapshot is not None and current != source_snapshot:
        raise IndexSourceChanged("source changed during parsing or embedding")
    # Projection rows use ON DELETE CASCADE. The document lock serializes this
    # canonical replacement with pgvector publication for that same document.
    db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id,
    ).delete(synchronize_session=False)

    node_ids: list[str] = []
    for idx, node in enumerate(nodes):
        text = _node_text(node)
        node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
        node_meta = getattr(node, "metadata", None) or {}
        db.add(
            DocumentChunk(
                document_id=document_id,
                node_id=node_id,
                user_id=user_id,
                source_kind=source_kind,
                chunk_index=idx,
                text=text,
                text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()
                if text
                else None,
                page_start=node_meta.get("page_start"),
                page_end=node_meta.get("page_end"),
                token_count=node_meta.get("token_count"),
                metadata_json=_chunk_metadata_json(node_meta),
                index_status=index_status,
            )
        )
        if node_id:
            node_ids.append(str(node_id))
    if commit:
        db.commit()
    return {"chunk_count": len(nodes), "node_ids": node_ids}


def read_indexable_chunks(db: Session, document_id: str) -> list[DocumentChunk]:
    """A document's LIVE chunks in chunk order — the fact source a projection rebuild
    reads from (plan §4.6.3: rebuild from Postgres facts, never reverse-infer
    from old projection rows). Excludes soft-deleted chunks (``deleted_at`` /
    ``index_status='deleted'``) so a rebuild never re-indexes removed content."""
    return (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.document_id == document_id,
            DocumentChunk.deleted_at.is_(None),
            DocumentChunk.index_status != "deleted",
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )


def read_document_text(
    db: Session, document_id: str, *, max_chars: int = 20000
) -> tuple[str, int]:
    """Concatenate a document's live chunks in order. Returns (text, chunk_count).

    Excludes soft-deleted chunks (``deleted_at`` / ``index_status='deleted'``) so
    a delete/update is reflected in reads immediately.
    """
    rows = (
        db.query(DocumentChunk.text)
        .filter(
            DocumentChunk.document_id == document_id,
            DocumentChunk.deleted_at.is_(None),
            DocumentChunk.index_status != "deleted",
        )
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not rows:
        return "", 0
    pieces = [r[0] for r in rows if r[0]]
    if not pieces:
        return "", 0
    return "\n\n".join(pieces)[:max_chars], len(pieces)


def delete_document_chunks(
    db: Session, document_id: str, *, commit: bool = True
) -> list[str]:
    """Delete a document's chunks; return their stable node_ids for index cleanup."""
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
