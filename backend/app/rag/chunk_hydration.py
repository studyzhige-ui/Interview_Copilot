"""Hydrate Milvus hits into fully-attributed chunk dicts from Postgres facts.

Milvus rows carry only the index copy (user_id / source_kind / document_id /
text); everything the answer page shows — document title, file name, page
span, chunk index — comes from the Postgres fact tables. This module is the
single hydrate + live-check step shared by retrieval, the
``search_knowledge`` tool, and offline evaluation.

Live check (the read-path safety net for lagging/failed Milvus deletes):

  * the chunk row still exists, ``deleted_at IS NULL`` and is fully indexed;
  * its knowledge document exists, is not soft-deleted and is ``ready``.

A hit whose ``node_id`` does not resolve here is dropped.
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
            DocumentChunk.index_status == "indexed",
            KnowledgeDocument.deleted_at.is_(None),
            KnowledgeDocument.status == "ready",
        )
        .all()
    )
    by_node: dict[str, dict[str, Any]] = {}
    for chunk, doc, asset in rows:
        meta = _chunk_metadata(chunk.metadata_json)
        by_node[chunk.node_id] = {
            # Internal tenant provenance used by evaluation and diagnostics.
            # Context/source rendering intentionally omits it from user output.
            "user_id": doc.user_id,
            "chunk_id": chunk.id,
            "node_id": chunk.node_id,
            "document_id": chunk.document_id,
            "document_title": doc.title,
            "file_name": asset.original_filename if asset else None,
            "category": doc.category,
            "source_kind": chunk.source_kind,
            # Page span: best-effort provenance columns (Phase B migration
            # 0041). NULL for page-less formats.
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "chunk_index": chunk.chunk_index,
            "section_title": meta.get("section_title"),
            "heading_path": meta.get("heading_path"),
            "text": chunk.text,
        }
    return [by_node[nid] for nid in node_ids if nid in by_node]


__all__ = ["hydrate_chunks"]
