"""Read/write the ``document_chunks`` Postgres fact table.

This is the project's chunk store — it replaced the LlamaIndex
``PostgresDocumentStore`` for the knowledge base. Ingestion writes chunk rows
here (alongside the Milvus hybrid index); full-text reconstruction reads from
here. BM25 retrieval is served server-side by Milvus, not from this table.
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
# metadata_json (plan §4.4.2/§4.4.3/§4.5.4). NOT including category — that lives
# on knowledge_documents and is hydrated from there (INGEST-CLEANUP). Warnings
# are not a top-level key — they live inside their owning profile dict
# (cleaning_profile.warnings; parser_profile / splitter_profile later).
# parser_* / ocr_used producers land in B5.
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
    payload = {k: node_meta[k] for k in _METADATA_JSON_KEYS if node_meta.get(k) is not None}
    return json.dumps(payload, ensure_ascii=False) if payload else None


def write_chunks(
    db: Session,
    *,
    nodes: list[Any],
    user_id: int,
    source_kind: str,
    document_id: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Persist LlamaIndex ``nodes`` as ``document_chunks`` rows.

    Idempotent per document: when ``document_id`` is set, any existing chunks
    for it are replaced (re-ingest produces a fresh chunk set). Per-chunk
    provenance (page/token columns + diagnostic metadata_json) is lifted off
    each node's metadata, stamped by the parser / cleaning / chunking stages.
    Returns the chunk + node-id summary the worker stores on the document.
    """
    if document_id is not None:
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
                text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
                page_start=node_meta.get("page_start"),
                page_end=node_meta.get("page_end"),
                token_count=node_meta.get("token_count"),
                metadata_json=_chunk_metadata_json(node_meta),
                # Callers write Milvus before persisting chunks, so the index is
                # already live by the time the fact rows land.
                index_status="indexed",
            )
        )
        if node_id:
            node_ids.append(str(node_id))
    if commit:
        db.commit()
    return {"chunk_count": len(nodes), "node_ids": node_ids}


def read_document_text(db: Session, document_id: str, *, max_chars: int = 20000) -> tuple[str, int]:
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
