import json
import logging
import os
import time

from llama_index.core import Settings

from app.rag.chunking import chunk_document
from app.rag.cleaning import EmptyContentError, canonicalize_document
from app.rag.documents import ParsedDocument, ParsedPage

logger = logging.getLogger(__name__)


def _node_text(node) -> str:
    """Extract the raw chunk persisted as the Postgres answer fact.

    Milvus receives a separate deterministic retrieval view built from this
    text plus structural metadata; hydration always returns this raw fact.
    """
    text = getattr(node, "text", None)
    if not text and hasattr(node, "get_content"):
        try:
            text = node.get_content()
        except Exception:  # noqa: BLE001
            text = None
    return str(text or "")


def _node_id(node) -> str:
    return str(getattr(node, "node_id", None) or getattr(node, "id_", None) or "")


def _drop_blank_nodes(all_nodes: list) -> list:
    """Drop chunks whose text is empty / whitespace-only before embedding (plan
    §4.5.2): some providers reject empty input, and a blank chunk carries no
    retrievable signal. Filtering here (before BOTH Milvus and Postgres writes)
    keeps the index and the fact rows in sync. Warns with the dropped count."""
    kept = [n for n in all_nodes if _node_text(n).strip()]
    dropped = len(all_nodes) - len(kept)
    if dropped:
        logger.warning(
            "Dropped %d blank/whitespace chunk(s) before embedding.", dropped
        )
    return kept


def _embed_texts(texts: list[str]) -> tuple[list, dict]:
    """Embed chunk texts and validate the result before any index write (plan
    §4.5.2/§4.5.3). Returns ``(embeddings, embedding_profile)``.

    Raises :class:`EmbeddingValidationError` (permanent, non-retryable) when the
    vector count != chunk count or any vector's dim != ``EMBEDDING_DIM`` — so a
    misconfigured model fails the whole document loudly instead of writing a
    partial / dimension-mismatched index. The profile is observability only
    (plan §4.5.4); it rides into ``metadata_json``, never into Milvus scalars.
    """
    from app.rag.embedding_registry import EmbeddingValidationError, resolve_embedding

    cfg = resolve_embedding()
    batch_size = getattr(Settings.embed_model, "embed_batch_size", None)
    t0 = time.perf_counter()
    embeddings = Settings.embed_model.get_text_embedding_batch(
        texts, show_progress=True
    )
    duration_ms = int((time.perf_counter() - t0) * 1000)

    if len(embeddings) != len(texts):
        raise EmbeddingValidationError(
            f"向量数量({len(embeddings)})与文本块数量({len(texts)})不一致，已中止入库以避免部分索引。"
        )
    for emb in embeddings:
        if len(emb) != cfg.dim:
            raise EmbeddingValidationError(
                f"向量维度({len(emb)})与配置 EMBEDDING_DIM({cfg.dim})不一致；"
                f"请确认 embedding 模型与配置匹配，或重建索引。"
            )

    profile = {
        "embedding_provider": cfg.provider_id,
        "embedding_model": cfg.model,
        "embedding_dim": cfg.dim,
        "embedding_batch_size": batch_size,
        "embedding_duration_ms": duration_ms,
        "embedding_chunk_count": len(texts),
    }
    return embeddings, profile


def _document_title(document_id: str) -> str | None:
    from app.db.database import SessionLocal
    from app.models.knowledge import KnowledgeDocument

    with SessionLocal() as db:
        row = db.query(KnowledgeDocument.title).filter_by(id=document_id).one_or_none()
    return str(row[0]) if row and row[0] else None


def _retrieval_texts(
    nodes: list,
    texts: list[str],
    *,
    document_title: str | None,
) -> list[str]:
    from app.rag.retrieval_text import build_retrieval_text

    def metadata(node) -> dict:
        value = getattr(node, "metadata", None)
        if isinstance(value, dict):
            return value
        raw = getattr(node, "metadata_json", None)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    output: list[str] = []
    for node, text in zip(nodes, texts):
        node_metadata = metadata(node)
        output.append(
            build_retrieval_text(
                text,
                document_title=document_title,
                section_title=node_metadata.get("section_title"),
                heading_path=node_metadata.get("heading_path"),
            )
        )
    return output


def _insert_milvus_rows(
    all_nodes: list,
    texts: list[str],
    embeddings: list,
    *,
    user_id: int,
    source_kind: str,
    document_id: str,
) -> None:
    """Insert the (precomputed) dense vectors into the Milvus 2.6 hybrid
    collection. The sparse/BM25 vector is produced server-side from ``text`` by
    the collection's BM25 ``Function`` — we supply only dense + text + scope
    fields (``user_id`` is the stable users.id pk). Re-ingesting a document
    replaces its prior rows first. Embedding + validation happen earlier in
    :func:`_index_nodes`; this is purely the index write (phase 2).
    """
    from app.rag import milvus_hybrid

    rows: list[dict] = []
    for node, text, emb in zip(all_nodes, texts, embeddings):
        rows.append(
            {
                "id": _node_id(node),
                "user_id": int(user_id),
                "source_kind": source_kind,
                "document_id": document_id,
                "text": text,
                "dense": emb,
            }
        )
    milvus_hybrid.delete_by_field(milvus_hybrid.KNOWLEDGE, "document_id", document_id)
    milvus_hybrid.insert(milvus_hybrid.KNOWLEDGE, rows)


def reindex_document(db, document_id: str) -> int:
    """Rebuild one document's Milvus rows from its LIVE Postgres chunks (plan
    §4.6.3) — the fact source, never the old Milvus rows. Builds the structural
    retrieval view, re-embeds it with the current model, replaces the document's
    rows (delete-by-document_id then insert, so a retry is idempotent), and flips
    any ``pending`` chunks to ``indexed``. Returns the row count written; 0 means
    no live chunks remain, in which case the document's Milvus rows are cleared.

    Used by the Milvus upsert/reindex outbox handlers and the reingest script.
    """
    from app.rag import milvus_hybrid
    from app.rag.document_chunk_service import (
        mark_chunks_indexed,
        read_indexable_chunks,
    )

    chunks = read_indexable_chunks(db, document_id)
    if not chunks:
        milvus_hybrid.delete_by_field(
            milvus_hybrid.KNOWLEDGE, "document_id", document_id
        )
        return 0
    texts = [(c.text or "") for c in chunks]
    retrieval_texts = _retrieval_texts(
        chunks,
        texts,
        document_title=_document_title(document_id),
    )
    embeddings, _profile = _embed_texts(retrieval_texts)
    # Chunks carry .node_id / .text, so _insert_milvus_rows treats them as nodes;
    # user_id / source_kind are uniform per document.
    _insert_milvus_rows(
        chunks,
        retrieval_texts,
        embeddings,
        user_id=int(chunks[0].user_id),
        source_kind=chunks[0].source_kind or "",
        document_id=document_id,
    )
    mark_chunks_indexed(db, document_id=document_id)
    return len(chunks)


def _index_nodes(
    all_nodes: list,
    *,
    user_id: int,
    source_kind: str,
    document_id: str,
) -> dict:
    """Document-atomic two-phase write (plan §4.6.3), shared by both ingest
    paths so they keep identical Milvus/Postgres semantics:

      embed + validate  →  write facts as ``pending``  →  Milvus rows  →  mark ``indexed``

    Embedding (dim/count) is validated FIRST, so a bad embedding fails the whole
    document before any row is written. Facts land as ``pending`` before Milvus.
    If the Milvus write then fails (outage), the committed pending facts are kept
    and a ``milvus_upsert_document`` outbox job is queued to retry the index
    write (§4.6.0 #6); ``chunk_info["indexed"]`` is ``False`` so the caller
    leaves the document ``processing`` until the index lands (the upsert handler
    flips it ready, or failed if the retries exhaust). Returns the
    ``write_chunks`` summary (chunk_count + node_ids + indexed).
    """
    from app.db.database import SessionLocal
    from app.rag.document_chunk_service import mark_chunks_indexed, write_chunks

    node_ids = [_node_id(node) for node in all_nodes]
    if any(not node_id for node_id in node_ids) or len(set(node_ids)) != len(node_ids):
        raise ValueError("chunks must have non-empty, unique node ids")

    texts = [_node_text(n) for n in all_nodes]
    retrieval_texts = _retrieval_texts(
        all_nodes,
        texts,
        document_title=_document_title(document_id),
    )
    embeddings, embedding_profile = _embed_texts(retrieval_texts)
    for node in all_nodes:
        node.metadata["embedding_profile"] = embedding_profile

    # Phase 1: facts first, as pending (replacement happens here).
    with SessionLocal() as db:
        chunk_info = write_chunks(
            db,
            nodes=all_nodes,
            user_id=user_id,
            source_kind=source_kind,
            document_id=document_id,
            index_status="pending",
        )
    # Phase 2: Milvus rows. On failure, keep the pending facts and queue a
    # reliable upsert retry rather than failing the import.
    try:
        _insert_milvus_rows(
            all_nodes,
            retrieval_texts,
            embeddings,
            user_id=user_id,
            source_kind=source_kind,
            document_id=document_id,
        )
    except Exception as exc:  # noqa: BLE001 — queue retry, don't fail the import
        logger.warning(
            "Milvus write failed for document %s; queuing upsert retry: %s",
            document_id,
            exc,
        )
        # Deliberate upward seam (rag → services.knowledge): the outbox is the
        # cross-system reliability layer, and enqueueing the retry job is the
        # only thing this pipeline needs from it — only on this failure path.
        from app.services.knowledge.index_jobs import enqueue_milvus_upsert

        with SessionLocal() as db:
            enqueue_milvus_upsert(db, user_pk=user_id, document_id=document_id)
            db.commit()
        chunk_info["indexed"] = False
        return chunk_info
    # Phase 3: flip the now-live rows to indexed.
    with SessionLocal() as db:
        mark_chunks_indexed(db, document_id=document_id)
    chunk_info["indexed"] = True
    return chunk_info


async def ingest_document(
    file_path: str,
    source_kind: str,
    user_id: int,
    *,
    document_id: str,
    upload_id: str | None = None,
):
    """
    文档摄取入口：解析文件 → 自适应切块 → 写入 Milvus 索引 + Postgres document_chunks。
    P0 安全：强制绑定 user_id 执行多租户物理隔离。
    """
    try:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"未找到待摄取的档案: {file_path}")

        logger.info(f"开始解析文件: {file_path}")

        # The parser registry produces the single canonical representation
        # consumed by every downstream stage.
        from app.rag.parsing import parse_document

        canonical = parse_document(file_path)

        metadata: dict = {
            "source_kind": source_kind,
            "user_id": user_id,
            "file_name": os.path.basename(file_path),  # drives splitter selection
        }
        metadata["document_id"] = document_id
        if upload_id:
            metadata["upload_id"] = upload_id
        all_nodes = chunk_document(
            canonical,
            metadata=metadata,
            document_title=_document_title(document_id),
        )

        all_nodes = _drop_blank_nodes(all_nodes)
        if not all_nodes:
            raise EmptyContentError("内容切分后没有可索引的有效文本块。")

        for node in all_nodes:
            node.metadata["document_id"] = document_id
            if upload_id:
                node.metadata["upload_id"] = upload_id

        # Two-phase document-atomic write (§4.6.3): facts pending → Milvus →
        # indexed. Postgres document_chunks is the fact source; Milvus is the
        # rebuildable index copy.
        logger.info(f">>> 索引 {len(all_nodes)} 个节点 (pending→Milvus→indexed)...")
        chunk_info = _index_nodes(
            all_nodes,
            user_id=user_id,
            source_kind=source_kind,
            document_id=document_id,
        )

        logger.info(
            f">>> 摄取完成: '{file_path}' (source_kind={source_kind}, user_id={user_id})"
        )

        # Denormalised document body for knowledge_documents.content_text
        # (display / reindex). Chunks remain the chunk-level fact source.
        full_text = canonical.text[:200000]
        return {
            "success": True,
            "indexed": chunk_info.get("indexed", True),
            "chunk_count": chunk_info["chunk_count"],
            "node_ids": chunk_info["node_ids"],
            "ref_doc_ids": list(
                {node.ref_doc_id for node in all_nodes if node.ref_doc_id}
            ),
            "content_text": full_text,
        }

    except Exception as e:
        logger.error(f"文档摄取失败: {e}")
        raise


async def ingest_text(
    text: str,
    source_kind: str,
    user_id: int,
    *,
    document_id: str,
):
    """Index text owned by one ``knowledge_documents`` row."""
    try:
        final_metadata: dict = {
            "source_kind": source_kind,
            "user_id": user_id,
            "document_id": document_id,
        }

        canonical = canonicalize_document(
            ParsedDocument(
                pages=[ParsedPage(text=text)],
                parser_id="text_input",
                content_kind=("markdown" if source_kind == "improved_qa" else "text"),
            ),
            parser_profile={"tier": "native", "fallback_used": False},
        )
        all_nodes = _drop_blank_nodes(
            chunk_document(
                canonical,
                metadata=final_metadata,
                document_title=_document_title(document_id),
            )
        )
        if not all_nodes:
            raise EmptyContentError("内容切分后没有可索引的有效文本块。")
        for node in all_nodes:
            node.metadata["document_id"] = document_id

        # Same two-phase write as file ingestion: facts → index → ready facts.
        logger.info(
            f"纯文本摄取: 索引 {len(all_nodes)} 个节点 (pending→Milvus→indexed)..."
        )
        chunk_info = _index_nodes(
            all_nodes,
            user_id=user_id,
            source_kind=source_kind,
            document_id=document_id,
        )

        logger.info(f"文本摄取完成 (source_kind='{source_kind}')。")

        return {
            "success": True,
            "indexed": chunk_info.get("indexed", True),
            "chunk_count": chunk_info["chunk_count"],
            "node_ids": chunk_info["node_ids"],
            "ref_doc_ids": list(
                {node.ref_doc_id for node in all_nodes if node.ref_doc_id}
            ),
        }
    except Exception as e:
        logger.error(f"文本摄取失败: {e}")
        raise
