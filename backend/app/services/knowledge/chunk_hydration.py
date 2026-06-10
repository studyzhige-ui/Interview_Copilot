"""Hydrate Milvus hits into fully-attributed chunk dicts from Postgres facts.

Milvus rows carry only the index copy (user_id / source_kind / document_id /
text); everything the answer page shows — document title, file name, page
span, chunk index — comes from the Postgres fact tables. This module is the
single hydrate + live-check step shared by the L1 retriever, the L2
``search_knowledge`` tool and the evaluation runners.

Live check (the read-path safety net for lagging/failed Milvus deletes):

  * the chunk row still exists, ``deleted_at IS NULL`` and
    ``index_status != 'deleted'`` — ``failed`` is an index-copy state; the
    Postgres text is still the fact source, so it does NOT hide a chunk
    (ingestion plan §4.4.1);
  * its knowledge document exists, is not soft-deleted and is not in a
    deleting/delete_failed state.

A hit whose ``node_id`` doesn't resolve here is dropped. This also covers
legacy index rows whose chunk rows were removed by migration (e.g. the old
personal_memory corpus, dropped in 0039) — replacing the explicit
source_kind exclusion the retriever used to carry.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument

logger = logging.getLogger(__name__)

# Knowledge-document states that mean "no longer a valid read source".
KB_DEAD_DOC_STATES = {"deleting", "delete_failed", "deleted"}


def _chunk_metadata(raw: str | None) -> dict[str, Any]:
    """Parse ``metadata_json`` defensively — it's a long-tail diagnostics
    container, never trusted to be well-formed."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def hydrate_chunks(db: Session, node_ids: list[str]) -> list[dict[str, Any]]:
    """Resolve Milvus ``node_id`` hits to live, fully-attributed chunk dicts.

    Returns dicts in the SAME order as ``node_ids``; hits that fail the live
    check (or never had a fact row) are silently dropped. ``text`` is the
    Postgres fact text, not the (possibly truncated) Milvus copy.
    """
    if not node_ids:
        return []
    rows = (
        db.query(DocumentChunk, KnowledgeDocument, FileAsset)
        .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
        .outerjoin(FileAsset, KnowledgeDocument.file_asset_id == FileAsset.id)
        .filter(
            DocumentChunk.node_id.in_(node_ids),
            DocumentChunk.deleted_at.is_(None),
            DocumentChunk.index_status != "deleted",
            KnowledgeDocument.deleted_at.is_(None),
            ~KnowledgeDocument.status.in_(KB_DEAD_DOC_STATES),
        )
        .all()
    )
    by_node: dict[str, dict[str, Any]] = {}
    for chunk, doc, asset in rows:
        meta = _chunk_metadata(chunk.metadata_json)
        by_node[chunk.node_id] = {
            "chunk_id": chunk.id,
            "node_id": chunk.node_id,
            "document_id": chunk.document_id,
            "document_title": doc.title,
            "file_name": asset.original_filename if asset else None,
            "content_type": asset.content_type if asset else None,
            "size_bytes": asset.size_bytes if asset else None,
            "category": doc.category,
            "source_kind": chunk.source_kind,
            # Page span / token_count are doc-contract source fields whose
            # columns land with the Phase-B ingestion migration. Explicit None
            # (not getattr) so a future column-name mismatch fails loud when
            # Phase B wires the real values in.
            "page_start": None,
            "page_end": None,
            "token_count": None,
            "chunk_index": chunk.chunk_index,
            "section_title": meta.get("section_title"),
            "heading_path": meta.get("heading_path"),
            "chunk_type": meta.get("chunk_type"),
            "text": chunk.text,
            "text_hash": chunk.text_hash,
        }
    return [by_node[nid] for nid in node_ids if nid in by_node]


__all__ = ["KB_DEAD_DOC_STATES", "hydrate_chunks"]
