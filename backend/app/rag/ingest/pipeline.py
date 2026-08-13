"""Canonical knowledge ingestion pipeline.

There is one write order for file uploads, text documents, and reindex jobs:
parse → quality gate → chunk → stable ids → embed → pending facts → versioned
Milvus rows → atomic Postgres publication.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from app.db import database as database_module
from app.models.knowledge import KnowledgeDocument
from app.rag.chunking import chunk_document
from app.rag.cleaning import EmptyContentError, canonicalize_document
from app.rag.documents import ParsedDocument, ParsedPage
from app.rag.index.knowledge import replace_document_rows
from app.rag.index.publication import publish_document
from app.rag.ingest.embedding import (
    build_retrieval_passages,
    drop_blank_nodes,
    embed_passages,
    node_id,
    node_text,
)

logger = logging.getLogger(__name__)


def _document_title(document_id: str) -> str | None:
    with database_module.SessionLocal() as db:
        value = (
            db.query(KnowledgeDocument.title)
            .filter(KnowledgeDocument.id == document_id)
            .scalar()
        )
    return str(value) if value else None


def _stamp_stable_ids(nodes: list[Any], document_id: str) -> None:
    """Give deterministic ids to a stable chunking result."""

    for index, node in enumerate(nodes):
        payload = f"{document_id}\0{index}\0{node_text(node)}"
        stable_id = "rag_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]
        node.id_ = stable_id


def _validate_node_ids(nodes: list[Any]) -> list[str]:
    node_ids = [node_id(node) for node in nodes]
    if any(not value for value in node_ids) or len(set(node_ids)) != len(node_ids):
        raise ValueError("chunks must have non-empty, unique node ids")
    return node_ids


def _persist_nodes(
    nodes: list[Any],
    *,
    user_id: int,
    source_kind: str,
    document_id: str,
    embed_model: Any | None = None,
    document_title_loader=_document_title,
    assign_stable_ids: bool = True,
    index_document: bool = True,
) -> dict[str, Any]:
    from app.rag.document_chunk_service import write_chunks

    if assign_stable_ids:
        _stamp_stable_ids(nodes, document_id)
    _validate_node_ids(nodes)
    if not index_document:
        # Conversation attachments are private facts, not global knowledge.
        # Persist their parsed chunks for exact reads / per-turn grounding, but
        # never embed or publish them into the user's Milvus collection. A
        # read-time post-filter would be too late: private rows could already
        # have displaced library candidates from Milvus' top-k result.
        with database_module.SessionLocal() as db:
            chunk_info = write_chunks(
                db,
                nodes=nodes,
                user_id=user_id,
                source_kind=source_kind,
                document_id=document_id,
                index_status="private",
            )
        return {**chunk_info, "indexed": True, "vector_indexed": False}

    passages = build_retrieval_passages(
        nodes,
        document_title=document_title_loader(document_id),
    )
    batch = embed_passages(passages, embed_model=embed_model)
    for node in nodes:
        node.metadata["embedding_profile"] = batch.profile

    with database_module.SessionLocal() as db:
        chunk_info = write_chunks(
            db,
            nodes=nodes,
            user_id=user_id,
            source_kind=source_kind,
            document_id=document_id,
            index_status="pending",
        )

    try:
        replace_document_rows(
            nodes,
            passages,
            batch.vectors,
            user_id=user_id,
            source_kind=source_kind,
            document_id=document_id,
        )
    except Exception as exc:  # external index is repaired through the outbox
        logger.warning(
            "Versioned index write failed for document %s; queued for retry: %s",
            document_id,
            exc,
        )
        from app.services.knowledge.index_jobs import enqueue_milvus_upsert

        with database_module.SessionLocal() as db:
            enqueue_milvus_upsert(db, user_pk=user_id, document_id=document_id)
            db.commit()
        return {**chunk_info, "indexed": False}

    with database_module.SessionLocal() as db:
        publish_document(db, document_id)
    return {**chunk_info, "indexed": True}


def _prepare_nodes(
    canonical,
    *,
    metadata: dict[str, Any],
    document_id: str,
    chunker=chunk_document,
    document_title_loader=_document_title,
) -> list[Any]:
    nodes = drop_blank_nodes(
        chunker(
            canonical,
            metadata=metadata,
            document_title=document_title_loader(document_id),
        )
    )
    if not nodes:
        raise EmptyContentError("内容切分后没有可索引的有效文本块。")
    for node in nodes:
        node.metadata["document_id"] = document_id
    return nodes


async def ingest_document(
    file_path: str,
    source_kind: str,
    user_id: int,
    *,
    document_id: str,
    upload_id: str | None = None,
    _chunker=chunk_document,
    _document_title_loader=_document_title,
    _embed_model: Any | None = None,
    index_document: bool = True,
) -> dict[str, Any]:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"未找到待摄取的档案: {file_path}")
    from app.rag.parsing import parse_document

    canonical = parse_document(file_path)
    metadata: dict[str, Any] = {
        "source_kind": source_kind,
        "user_id": user_id,
        "file_name": os.path.basename(file_path),
        "document_id": document_id,
    }
    if upload_id:
        metadata["upload_id"] = upload_id
    nodes = _prepare_nodes(
        canonical,
        metadata=metadata,
        document_id=document_id,
        chunker=_chunker,
        document_title_loader=_document_title_loader,
    )
    for node in nodes:
        if upload_id:
            node.metadata["upload_id"] = upload_id
    chunk_info = _persist_nodes(
        nodes,
        user_id=user_id,
        source_kind=source_kind,
        document_id=document_id,
        embed_model=_embed_model,
        document_title_loader=_document_title_loader,
        index_document=index_document,
    )
    return {
        "success": True,
        "indexed": chunk_info["indexed"],
        "vector_indexed": chunk_info.get("vector_indexed", True),
        "chunk_count": chunk_info["chunk_count"],
        "node_ids": chunk_info["node_ids"],
        "ref_doc_ids": list({node.ref_doc_id for node in nodes if node.ref_doc_id}),
        "content_text": canonical.text[:200000],
    }


async def ingest_text(
    text: str,
    source_kind: str,
    user_id: int,
    *,
    document_id: str,
    _chunker=chunk_document,
    _document_title_loader=_document_title,
    _embed_model: Any | None = None,
) -> dict[str, Any]:
    return await _ingest_textual_source(
        text,
        source_kind,
        user_id,
        document_id=document_id,
        parser_id="text_input",
        content_kind="markdown" if source_kind == "improved_qa" else "text",
        parser_profile={"tier": "native", "fallback_used": False},
        chunker=_chunker,
        document_title_loader=_document_title_loader,
        embed_model=_embed_model,
        index_document=True,
    )


async def ingest_transcript(
    text: str,
    source_kind: str,
    user_id: int,
    *,
    document_id: str,
    upload_id: str,
    _chunker=chunk_document,
    _document_title_loader=_document_title,
) -> dict[str, Any]:
    """Persist an audio transcript as a private, citable text projection.

    The original media remains owned by ``FileAsset``.  This function only
    writes the same rebuildable ``KnowledgeDocument`` chunks used by other
    Conversation attachments; it never publishes audio-derived text into the
    user's global Milvus collection.
    """

    return await _ingest_textual_source(
        text,
        source_kind,
        user_id,
        document_id=document_id,
        upload_id=upload_id,
        parser_id="audio_transcription",
        content_kind="transcript",
        parser_profile={
            "tier": "transcription",
            "fallback_used": False,
            "warnings": ["当前来源由音频转写生成，未检查音画内容或视觉布局。"],
        },
        chunker=_chunker,
        document_title_loader=_document_title_loader,
        embed_model=None,
        index_document=False,
    )


async def _ingest_textual_source(
    text: str,
    source_kind: str,
    user_id: int,
    *,
    document_id: str,
    parser_id: str,
    content_kind: str,
    parser_profile: dict[str, Any],
    upload_id: str | None = None,
    chunker=chunk_document,
    document_title_loader=_document_title,
    embed_model: Any | None = None,
    index_document: bool,
) -> dict[str, Any]:
    canonical = canonicalize_document(
        ParsedDocument(
            pages=[ParsedPage(text=text)],
            parser_id=parser_id,
            content_kind=content_kind,
        ),
        parser_profile=parser_profile,
    )
    metadata = {
        "source_kind": source_kind,
        "user_id": user_id,
        "document_id": document_id,
    }
    if upload_id:
        metadata["upload_id"] = upload_id
    nodes = _prepare_nodes(
        canonical,
        metadata=metadata,
        document_id=document_id,
        chunker=chunker,
        document_title_loader=document_title_loader,
    )
    if upload_id:
        for node in nodes:
            node.metadata["upload_id"] = upload_id
    chunk_info = _persist_nodes(
        nodes,
        user_id=user_id,
        source_kind=source_kind,
        document_id=document_id,
        embed_model=embed_model,
        document_title_loader=document_title_loader,
        index_document=index_document,
    )
    return {
        "success": True,
        "indexed": chunk_info["indexed"],
        "vector_indexed": chunk_info.get("vector_indexed", True),
        "chunk_count": chunk_info["chunk_count"],
        "node_ids": chunk_info["node_ids"],
        "ref_doc_ids": list({node.ref_doc_id for node in nodes if node.ref_doc_id}),
        "content_text": canonical.text[:200000],
    }


__all__ = ["ingest_document", "ingest_text", "ingest_transcript"]
