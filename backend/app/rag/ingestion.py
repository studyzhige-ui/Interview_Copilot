import os
import logging
import re
import time
from llama_index.core import Document, Settings
from llama_index.core.node_parser import SentenceSplitter
from app.core.config import settings
from app.rag.chunking import CHUNK_OVERLAP, CHUNK_SIZE, select_splitter
from app.rag.cleaning import EmptyContentError, clean_text
from app.rag.embedding_tokenizer import count_tokens as count_embedding_tokens

logger = logging.getLogger(__name__)


def _clean_documents(documents: list) -> list:
    """Apply S0 cleaning (plan §4.2) to each parsed document, keeping only
    those with usable text. Quality warnings are logged (not persisted —
    per-chunk diagnostic metadata_json lands in B4). Raises
    :class:`EmptyContentError` when no usable text remains anywhere."""
    if not settings.RAG_CLEANING_ENABLED:
        return documents
    kept: list = []
    for doc in documents:
        cleaned, profile = clean_text(doc.text or "")
        if not cleaned:
            logger.warning("S0 cleaning emptied a document segment; dropping it.")
            continue
        if profile.warnings:
            logger.warning("S0 cleaning warnings: %s", profile.warnings)
        doc.set_content(cleaned)
        # Document-level diagnostic; propagates to every chunk's node.metadata
        # (parsers copy doc metadata) and lands in document_chunks.metadata_json.
        doc.metadata["cleaning_profile"] = profile.as_dict()
        kept.append(doc)
    if not kept:
        raise EmptyContentError(
            "文档清洗后没有可用文本，请确认文件内容非空且为可读文本。"
        )
    return kept


def _node_text(node) -> str:
    """Extract a node's text (mirrors document_chunk_service so the Milvus
    ``text`` field and the Postgres fact row carry identical content)."""
    text = getattr(node, "text", None)
    if not text and hasattr(node, "get_content"):
        try:
            text = node.get_content()
        except Exception:  # noqa: BLE001
            text = None
    return str(text or "")


def _drop_blank_nodes(all_nodes: list) -> list:
    """Drop chunks whose text is empty / whitespace-only before embedding (plan
    §4.5.2): some providers reject empty input, and a blank chunk carries no
    retrievable signal. Filtering here (before BOTH Milvus and Postgres writes)
    keeps the index and the fact rows in sync. Warns with the dropped count."""
    kept = [n for n in all_nodes if _node_text(n).strip()]
    dropped = len(all_nodes) - len(kept)
    if dropped:
        logger.warning("Dropped %d blank/whitespace chunk(s) before embedding.", dropped)
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
    embeddings = Settings.embed_model.get_text_embedding_batch(texts, show_progress=True)
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


def _insert_milvus_rows(
    all_nodes: list, texts: list[str], embeddings: list,
    *, user_id: int, source_kind: str, document_id: str | None,
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
        node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
        if not node_id:
            continue
        rows.append({
            "id": str(node_id),
            "user_id": int(user_id),
            "source_kind": source_kind,
            "document_id": document_id,
            "text": text,
            "dense": emb,
        })
    if document_id:
        milvus_hybrid.delete_by_field(milvus_hybrid.KNOWLEDGE, "document_id", document_id)
    milvus_hybrid.insert(milvus_hybrid.KNOWLEDGE, rows)


def reindex_document(db, document_id: str) -> int:
    """Rebuild one document's Milvus rows from its LIVE Postgres chunks (plan
    §4.6.3) — the fact source, never the old Milvus rows. Re-embeds chunk text
    with the current model, replaces the document's rows (delete-by-document_id
    then insert, so a retry is idempotent), and flips any ``pending`` chunks to
    ``indexed``. Returns the row count written; 0 means no live chunks remain,
    in which case the document's Milvus rows are simply cleared.

    Used by the Milvus upsert/reindex outbox handlers and the reingest script.
    """
    from app.rag import milvus_hybrid
    from app.services.knowledge.document_chunk_service import (
        mark_chunks_indexed,
        read_indexable_chunks,
    )

    chunks = read_indexable_chunks(db, document_id)
    if not chunks:
        milvus_hybrid.delete_by_field(milvus_hybrid.KNOWLEDGE, "document_id", document_id)
        return 0
    texts = [(c.text or "") for c in chunks]
    embeddings, _profile = _embed_texts(texts)
    # Chunks carry .node_id / .text, so _insert_milvus_rows treats them as nodes;
    # user_id / source_kind are uniform per document.
    _insert_milvus_rows(
        chunks, texts, embeddings,
        user_id=int(chunks[0].user_id), source_kind=chunks[0].source_kind or "",
        document_id=document_id,
    )
    mark_chunks_indexed(db, document_id=document_id)
    return len(chunks)


def _index_nodes(
    all_nodes: list, *, user_id: int, source_kind: str, document_id: str | None,
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
    from app.services.knowledge.document_chunk_service import mark_chunks_indexed, write_chunks

    texts = [_node_text(n) for n in all_nodes]
    embeddings, embedding_profile = _embed_texts(texts)
    for node in all_nodes:
        node.metadata["embedding_profile"] = embedding_profile

    # Phase 1: facts first, as pending (replacement happens here).
    with SessionLocal() as db:
        chunk_info = write_chunks(
            db, nodes=all_nodes, user_id=user_id, source_kind=source_kind,
            document_id=document_id, index_status="pending",
        )
    # Phase 2: Milvus rows. On failure, keep the pending facts and queue a
    # reliable upsert retry rather than failing the import.
    try:
        _insert_milvus_rows(
            all_nodes, texts, embeddings,
            user_id=user_id, source_kind=source_kind, document_id=document_id,
        )
    except Exception as exc:  # noqa: BLE001 — queue retry, don't fail the import
        if not document_id:
            raise  # no document_id to key the retry on (defensive NULL path)
        logger.warning(
            "Milvus write failed for document %s; queuing upsert retry: %s",
            document_id, exc,
        )
        from app.services.knowledge.knowledge_outbox import enqueue_milvus_upsert
        with SessionLocal() as db:
            enqueue_milvus_upsert(db, user_pk=user_id, document_id=document_id)
            db.commit()
        chunk_info["indexed"] = False
        return chunk_info
    # Phase 3: flip the now-live rows to indexed. Mark by document_id on the
    # live path; node_ids is only for the document-less path (so the unused key
    # isn't passed when document_id is present).
    with SessionLocal() as db:
        if document_id:
            mark_chunks_indexed(db, document_id=document_id)
        else:
            mark_chunks_indexed(db, node_ids=chunk_info["node_ids"])
    chunk_info["indexed"] = True
    return chunk_info


_MD_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)")


def _heading_annotations(node, splitter_id: str) -> tuple[list[str] | None, str | None]:
    """Best-effort heading provenance for a MARKDOWN chunk (plan §4.4.2).

    ``MarkdownNodeParser`` stamps ``header_path`` like ``/Cache/Redis/`` (the
    ANCESTOR heading chain). We parse that into ``heading_path`` and read the
    node's own leading ``# `` line as ``section_title``. Gated to the markdown
    splitter: for any other branch (code/html/json/table/sentence) we return
    ``(None, None)`` — otherwise a ``# `` Python/shell comment on a code chunk's
    first line would be mistaken for a heading. Best-effort, never guesses."""
    if splitter_id != "markdown":
        return None, None
    meta = getattr(node, "metadata", None) or {}
    heading_path = None
    raw = meta.get("header_path")
    if raw and raw.strip("/"):
        heading_path = [p for p in raw.split("/") if p]
    section_title = None
    first_line = node.get_content().lstrip().split("\n", 1)[0]
    m = _MD_HEADER_RE.match(first_line)
    if m:
        section_title = m.group(1).strip()
    return heading_path, section_title


def get_optimal_nodes(document: Document) -> list:
    """
    自适应切块引擎：基于文档类型和内容结构智能选择切分策略。

    对于 Markdown/JSON 等结构化文档，先按语义结构切分，再用 SentenceSplitter
    做二次兜底，防止单个 chunk 超过 Embedding 模型的最大 token 限制。
    """
    source_kind = document.metadata.get("source_kind", "")
    file_name = document.metadata.get("file_name", "").lower()
    is_markdown_parsed = document.metadata.get("is_markdown_parsed", False)

    # Pick the content-type chunking strategy (Phase E4). The strategy produces
    # the primary nodes + whether the conservative QA grouping fired; the
    # oversize gate + annotation below are shared across all strategies.
    splitter = select_splitter(file_name, source_kind, is_markdown_parsed)
    nodes, qa_regex_hit = splitter.split(document)
    splitter_id, chunk_type = splitter.id, splitter.chunk_type

    # 二次兜底：对超长 chunk 做再切分，确保不超过 embedding 模型 max_seq_length。
    # 超长判定使用真实 embedding tokenizer（plan §4.3），不再用 len(text) 字符估算。
    secondary_splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    final_nodes = []
    for node in nodes:
        text = node.get_content()
        if count_embedding_tokens(text) > CHUNK_SIZE * 2:
            sub_nodes = secondary_splitter.get_nodes_from_documents(
                [Document(text=text, metadata=node.metadata)]
            )
            final_nodes.extend(sub_nodes)
        else:
            final_nodes.append(node)

    # P0 级红线：阻止 NodeParser 洗掉原文档的 Metadata。同时落 token_count
    # （embedding tokenizer 口径）和诊断/溯源标注（splitter_id/chunk_type/
    # splitter_profile/cleaning_profile/heading_path/section_title），供
    # document_chunks 列与 metadata_json 持久化。
    user_id = document.metadata.get("user_id", "")
    cleaning_profile = document.metadata.get("cleaning_profile")
    # Parse-stage provenance (Phase E) — carried from the document metadata to
    # every chunk so it lands in metadata_json (the parser_id/parser_profile/
    # ocr_used producers B4 reserved). Absent on the ingest_text path (no file).
    parser_id = document.metadata.get("parser_id")
    parser_profile = document.metadata.get("parser_profile")
    ocr_used = document.metadata.get("ocr_used")
    # splitter_profile records the SentenceSplitter sizing regime — the secondary
    # oversize gate (CHUNK_SIZE*2) + fallback re-split that EVERY branch passes
    # through, stamped uniformly. The primary splitter's true identity is in
    # splitter_id; for the code (chunk_lines) and table (char_budget) branches
    # these chunk_size/overlap values describe the fallback regime, not the
    # primary boundaries. qa_regex_hit records whether the conservative QA-prefix
    # grouping fired (plan §4.4.3 "正则命中"); only ever True on the plain-text
    # branch, truthfully False everywhere else.
    splitter_profile = {
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "tokenizer": "embedding",
        "qa_regex_hit": qa_regex_hit,
    }
    for node in final_nodes:
        node.metadata["source_kind"] = source_kind
        if user_id:
            node.metadata["user_id"] = user_id
        node.metadata["token_count"] = count_embedding_tokens(node.get_content())
        node.metadata["splitter_id"] = splitter_id
        node.metadata["chunk_type"] = chunk_type
        node.metadata["splitter_profile"] = splitter_profile
        if cleaning_profile is not None:
            node.metadata["cleaning_profile"] = cleaning_profile
        if parser_id:
            node.metadata["parser_id"] = parser_id
        if parser_profile:
            node.metadata["parser_profile"] = parser_profile
        if ocr_used is not None:
            node.metadata["ocr_used"] = ocr_used
        heading_path, section_title = _heading_annotations(node, splitter_id)
        if heading_path:
            node.metadata["heading_path"] = heading_path
        if section_title:
            node.metadata["section_title"] = section_title

    return final_nodes


async def ingest_document(
    file_path: str,
    source_kind: str,
    user_id: int,
    *,
    document_id: str | None = None,
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

        # Parse stage (Phase E): one ParseResult from the parser registry, which
        # owns parser selection / fallback / error translation — this path no
        # longer binds to LlamaParse / PyMuPDF / SimpleDirectoryReader directly.
        # Empty / unparseable input raises EmptyContentError inside parse_document.
        from app.rag.parsing import parse_document

        result = parse_document(file_path)

        metadata: dict = {
            "source_kind": source_kind,
            "user_id": user_id,
            "file_name": os.path.basename(file_path),  # drives splitter selection
            "parser_id": result.parser_id,
            "parser_profile": result.parser_profile,
            "ocr_used": result.ocr_used,
        }
        if document_id:
            metadata["document_id"] = document_id
        if upload_id:
            metadata["upload_id"] = upload_id
        if result.is_markdown:
            metadata["is_markdown_parsed"] = True
        # category is NOT stamped onto chunks/metadata_json — it's a
        # knowledge_documents field, hydrated from there (INGEST-CLEANUP).
        doc = Document(text=result.markdown, metadata=metadata)
        if document_id:
            doc.id_ = document_id

        # S0 conservative cleaning (plan §4.2) before chunking; raises
        # EmptyContentError if no usable text remains.
        documents = _clean_documents([doc])

        # 自适应切块
        all_nodes = []
        for doc in documents:
            nodes = get_optimal_nodes(doc)
            all_nodes.extend(nodes)

        all_nodes = _drop_blank_nodes(all_nodes)
        if not all_nodes:
            raise EmptyContentError("内容切分后没有可索引的有效文本块。")

        for node in all_nodes:
            if document_id:
                node.metadata["document_id"] = document_id
            if upload_id:
                node.metadata["upload_id"] = upload_id

        # Two-phase document-atomic write (§4.6.3): facts pending → Milvus →
        # indexed. Postgres document_chunks is the fact source; Milvus is the
        # rebuildable index copy.
        logger.info(f">>> 索引 {len(all_nodes)} 个节点 (pending→Milvus→indexed)...")
        chunk_info = _index_nodes(
            all_nodes, user_id=user_id, source_kind=source_kind, document_id=document_id,
        )

        logger.info(f">>> 摄取完成: '{file_path}' (source_kind={source_kind}, user_id={user_id})")

        # Denormalised document body for knowledge_documents.content_text
        # (display / reindex). Chunks remain the chunk-level fact source.
        full_text = "\n\n".join((d.text or "") for d in documents)[:200000]
        return {
            "success": True,
            "indexed": chunk_info.get("indexed", True),
            "chunk_count": chunk_info["chunk_count"],
            "node_ids": chunk_info["node_ids"],
            "ref_doc_ids": list({node.ref_doc_id for node in all_nodes if node.ref_doc_id}),
            "content_text": full_text,
        }

    except Exception as e:
        logger.error(f"文档摄取失败: {e}")
        raise


async def ingest_text(
    text: str, source_kind: str, user_id: int,
    *, document_id: str | None = None,
):
    """纯文本节点摄取通道。P0 安全：强制执行多租户隔离。

    ``document_id`` ties the chunks + Milvus rows to a ``knowledge_documents``
    row (e.g. improved_qa) and is always set by the live callers. The
    document-less (NULL) path is retained only as defensive infrastructure —
    the former ``personal_memory`` writer was removed in MEMORY-V3 (long-term
    user state now lives in memory_ability_states, not the knowledge base).

    category is intentionally NOT taken/stamped here — it's a
    knowledge_documents field hydrated from there (INGEST-CLEANUP).
    """
    try:
        final_metadata: dict = {
            "source_kind": source_kind,
            "user_id": user_id,
        }
        if document_id:
            final_metadata["document_id"] = document_id

        # S0 cleaning (plan §4.2) — same conservative pass as file ingest.
        if settings.RAG_CLEANING_ENABLED:
            cleaned, profile = clean_text(text)
            if not cleaned:
                raise EmptyContentError("内容清洗后为空，无法入库。")
            if profile.warnings:
                logger.warning("S0 cleaning warnings: %s", profile.warnings)
            text = cleaned
            final_metadata["cleaning_profile"] = profile.as_dict()

        doc = Document(text=text, metadata=final_metadata)
        all_nodes = _drop_blank_nodes(get_optimal_nodes(doc))
        if not all_nodes:
            raise EmptyContentError("内容切分后没有可索引的有效文本块。")
        for node in all_nodes:
            if document_id:
                node.metadata["document_id"] = document_id

        # Two-phase document-atomic write (§4.6.3), shared with file ingest:
        # facts pending → Milvus → indexed. document_id NULL only on the
        # defensive document-less path; set for improved_qa etc.
        logger.info(f"纯文本摄取: 索引 {len(all_nodes)} 个节点 (pending→Milvus→indexed)...")
        chunk_info = _index_nodes(
            all_nodes, user_id=user_id, source_kind=source_kind, document_id=document_id,
        )

        logger.info(f"文本摄取完成 (source_kind='{source_kind}')。")

        return {
            "success": True,
            "indexed": chunk_info.get("indexed", True),
            "chunk_count": chunk_info["chunk_count"],
            "node_ids": chunk_info["node_ids"],
            "ref_doc_ids": list({node.ref_doc_id for node in all_nodes if node.ref_doc_id}),
        }
    except Exception as e:
        logger.error(f"文本摄取失败: {e}")
        raise
