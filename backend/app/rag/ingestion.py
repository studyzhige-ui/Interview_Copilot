import os
import logging
import re
import time
from llama_index.core import Document, Settings, SimpleDirectoryReader
from llama_index.readers.file import PyMuPDFReader
from llama_index.core.node_parser import (
    CodeSplitter,
    HTMLNodeParser,
    JSONNodeParser,
    MarkdownNodeParser,
    SentenceSplitter,
)
from app.core.config import settings
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


def _write_to_milvus_hybrid(
    all_nodes: list, *, user_id: int, source_kind: str, document_id: str | None,
) -> None:
    """Embed each node (dense) and insert into the Milvus 2.6 hybrid collection.

    The sparse/BM25 vector is computed server-side from ``text`` by the
    collection's BM25 ``Function`` — we only supply the dense vector + text +
    scope fields (``user_id`` is the stable users.id pk). Re-ingesting a document
    replaces its prior chunks first. The embedding is validated (dim + count)
    before any delete/insert, and its observability profile is stamped onto each
    node so ``write_chunks`` persists it in ``metadata_json``.
    """
    from app.rag import milvus_hybrid

    texts = [_node_text(n) for n in all_nodes]
    embeddings, embedding_profile = _embed_texts(texts)
    for node in all_nodes:
        node.metadata["embedding_profile"] = embedding_profile
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


def _code_splitter(language: str) -> CodeSplitter:
    """Build a CodeSplitter with an explicitly-constructed tree-sitter Parser.

    ``tree_sitter_language_pack.get_parser()`` returns the pack's own bundled
    Parser type, which fails LlamaIndex CodeSplitter's
    ``isinstance(_, tree_sitter.Parser)`` check. Building the Parser ourselves
    from the pack's Language + the pip ``tree_sitter`` satisfies it and keeps
    AST-aware code chunking working."""
    from tree_sitter import Parser
    from tree_sitter_language_pack import get_language

    parser = Parser(get_language(language))
    return CodeSplitter(
        language=language, chunk_lines=40, chunk_lines_overlap=5, parser=parser,
    )


def _table_aware_nodes(document: Document, char_budget: int) -> list:
    """Split CSV/XLSX-extracted text into row-group chunks, repeating the
    header in each chunk so a single retrieved chunk stays self-describing."""
    from llama_index.core.schema import TextNode

    lines = [ln for ln in (document.text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0]
    body = lines[1:] or [header]
    nodes: list = []
    buf: list[str] = []
    size = len(header)
    for row in body:
        if buf and size + len(row) > char_budget:
            nodes.append(TextNode(text=header + "\n" + "\n".join(buf), metadata=dict(document.metadata)))
            buf, size = [], len(header)
        buf.append(row)
        size += len(row) + 1
    if buf:
        nodes.append(TextNode(text=header + "\n" + "\n".join(buf), metadata=dict(document.metadata)))
    return nodes


# Explicit Q/A prefix markers (plan §4.3 "最保守 QA 正则"). Anchored to line
# start (re.MULTILINE) so a mid-sentence "问题：" never matches; both half- and
# full-width colons. Longest alternative first only avoids a backtrack ("问题："
# also matches via "问" + backtrack on the colon) — clarity, not correctness.
_QA_Q_RE = re.compile(r"^[ \t]*(?:问题|问|Q)[:：]", re.MULTILINE)
_QA_A_RE = re.compile(r"^[ \t]*(?:答案|答|A)[:：]", re.MULTILINE)


def _qa_aware_nodes(document: Document) -> list | None:
    """Most-conservative QA-prefix grouping for PLAIN TEXT (plan §4.3, rule 2).

    A plain-text question bank using explicit ``Q:``/``A:`` (or ``问题：``/
    ``答案：``) prefixes would otherwise be cut between a question and its answer
    by ``SentenceSplitter``. ONLY when the text shows a real paired structure
    (≥2 question markers AND ≥1 answer marker) do we split at question
    boundaries so each Q-and-its-A stays in one chunk; the downstream oversize
    gate still re-splits any group that is too long. Returns ``None`` when
    there is no clear QA structure — the caller then falls back to the sentence
    splitter (never guesses, and structured parsers are never overridden since
    this only runs on the plain-text branch)."""
    from llama_index.core.schema import TextNode

    text = document.text or ""
    q_starts = [m.start() for m in _QA_Q_RE.finditer(text)]
    # A single question isn't a bank — require ≥2 questions (so an incidental
    # line-start "问题：" can't reshape a doc) AND ≥1 answer (a bare question
    # list is rule-3 "hint only", never a forced split).
    if len(q_starts) < 2 or not _QA_A_RE.search(text):
        return None

    spans: list[str] = []
    head = text[: q_starts[0]].strip()
    if head:  # preamble before the first question — keep it, drop nothing
        spans.append(head)
    for i, start in enumerate(q_starts):
        end = q_starts[i + 1] if i + 1 < len(q_starts) else len(text)
        # Each span begins at a marker match, so .strip() is always non-empty.
        spans.append(text[start:end].strip())
    return [TextNode(text=s, metadata=dict(document.metadata)) for s in spans]


def get_optimal_nodes(document: Document) -> list:
    """
    自适应切块引擎：基于文档类型和内容结构智能选择切分策略。

    对于 Markdown/JSON 等结构化文档，先按语义结构切分，再用 SentenceSplitter
    做二次兜底，防止单个 chunk 超过 Embedding 模型的最大 token 限制。
    """
    # BGE-M3 最大支持 8192 tokens，但推荐 chunk 在 512 tokens 以内
    # 以获得最佳的 embedding 语义密度。
    CHUNK_SIZE = 512
    CHUNK_OVERLAP = 64

    source_kind = document.metadata.get("source_kind", "")
    file_name = document.metadata.get("file_name", "").lower()

    is_markdown_parsed = document.metadata.get("is_markdown_parsed", False)
    qa_regex_hit = False

    # Tabular files (CSV / XLSX): split by row groups and repeat the header in
    # every chunk so a retrieved chunk is independently understandable.
    # splitter_id / chunk_type are diagnostic annotations (plan §4.4.3/§4.4.2).
    if file_name.endswith((".csv", ".tsv", ".xlsx", ".xls")):
        nodes = _table_aware_nodes(document, CHUNK_SIZE * 2)
        splitter_id, chunk_type = "table", "table"
    else:
        parser = None
        if (
            is_markdown_parsed
            or file_name.endswith((".md", ".markdown"))
            or source_kind == "improved_qa"  # saved QA content_text is Markdown
        ):
            parser = MarkdownNodeParser()
            splitter_id, chunk_type = "markdown", "text"
        elif file_name.endswith((".html", ".htm")):
            # HTML-aware: keeps heading/section/list/table/code structure,
            # drops script/style/nav noise.
            parser = HTMLNodeParser()
            splitter_id, chunk_type = "html", "text"
        elif file_name.endswith(".json"):
            parser = JSONNodeParser()
            splitter_id, chunk_type = "json", "text"
        elif file_name.endswith(".py"):
            parser = _code_splitter("python")
            splitter_id, chunk_type = "code", "code"
        elif file_name.endswith(".java"):
            parser = _code_splitter("java")
            splitter_id, chunk_type = "code", "code"
        elif file_name.endswith(".cpp") or file_name.endswith(".c"):
            parser = _code_splitter("cpp")
            splitter_id, chunk_type = "code", "code"
        else:
            # Plain text: try the most-conservative QA-prefix grouping first so a
            # question stays with its answer; fall back to the sentence splitter
            # when there's no clear Q/A structure (plan §4.3, never guesses).
            splitter_id, chunk_type = "sentence", "text"
            qa_nodes = _qa_aware_nodes(document)
            if qa_nodes is not None:
                nodes = qa_nodes
                qa_regex_hit = True
            else:
                parser = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

        if parser is not None:
            nodes = parser.get_nodes_from_documents([document])

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

        # 动态文件提取器
        extractor_map = {}

        _has_llama_cloud = (
            settings.LLAMA_CLOUD_API_KEY
            and settings.LLAMA_CLOUD_API_KEY.strip()
            and not settings.LLAMA_CLOUD_API_KEY.startswith("your_")
        )

        if _has_llama_cloud:
            logger.info("检测到 LlamaCloud 密钥，启用 LlamaParse 解析器...")
            import nest_asyncio
            nest_asyncio.apply()
            from llama_parse import LlamaParse

            parser = LlamaParse(
                result_type="markdown",
                language="ch_sim",
                api_key=settings.LLAMA_CLOUD_API_KEY,
                num_workers=2
            )
            extractor_map[".pdf"] = parser
            extractor_map[".pptx"] = parser
            extractor_map[".docx"] = parser
        else:
            logger.info("未配置 LlamaCloud 密钥，使用 PyMuPDF 解析。")
            extractor_map[".pdf"] = PyMuPDFReader()

        reader = SimpleDirectoryReader(
            input_files=[file_path],
            file_extractor=extractor_map
        )
        documents = reader.load_data()

        if not documents:
            logger.warning(f"文件解析结果为空: {file_path}")
            return False

        # 挂载元数据
        for index, doc in enumerate(documents):
            doc.metadata["source_kind"] = source_kind
            doc.metadata["user_id"] = user_id
            if document_id:
                doc.metadata["document_id"] = document_id
                doc.id_ = document_id if len(documents) == 1 else f"{document_id}:{index}"
            if upload_id:
                doc.metadata["upload_id"] = upload_id
            # category is NOT stamped onto chunks/metadata_json — it's a
            # knowledge_documents field, hydrated from there (INGEST-CLEANUP).

            if _has_llama_cloud and doc.metadata.get("file_name", "").endswith((".pdf", ".pptx", ".docx")):
                doc.metadata["is_markdown_parsed"] = True

        # S0 conservative cleaning (plan §4.2) before chunking. Drop segments
        # that clean to nothing (e.g. a blank page); fail the whole import only
        # if no usable text remains anywhere.
        documents = _clean_documents(documents)

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

        # Milvus 2.6 native dense + server-side BM25 hybrid, then the Postgres
        # chunk fact rows. Re-ingest replaces this document's prior chunks.
        logger.info(f">>> 写入 Milvus hybrid 索引，共 {len(all_nodes)} 个节点...")
        _write_to_milvus_hybrid(
            all_nodes, user_id=user_id, source_kind=source_kind, document_id=document_id,
        )

        # Persist chunk TEXT to Postgres document_chunks — the fact source.
        from app.db.database import SessionLocal
        from app.services.knowledge.document_chunk_service import write_chunks
        with SessionLocal() as db:
            chunk_info = write_chunks(
                db, nodes=all_nodes, user_id=user_id, source_kind=source_kind,
                document_id=document_id,
            )

        logger.info(f">>> 摄取完成: '{file_path}' (source_kind={source_kind}, user_id={user_id})")

        # Denormalised document body for knowledge_documents.content_text
        # (display / reindex). Chunks remain the chunk-level fact source.
        full_text = "\n\n".join((d.text or "") for d in documents)[:200000]
        return {
            "success": True,
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

        logger.info(f"纯文本摄取: {len(all_nodes)} 个节点写入 Milvus hybrid...")
        _write_to_milvus_hybrid(
            all_nodes, user_id=user_id, source_kind=source_kind, document_id=document_id,
        )

        # Persist to document_chunks. document_id NULL for personal_memory;
        # set for improved_qa (so the doc owns its chunks + delete-by-id works).
        from app.db.database import SessionLocal
        from app.services.knowledge.document_chunk_service import write_chunks
        with SessionLocal() as db:
            chunk_info = write_chunks(
                db, nodes=all_nodes, user_id=user_id, source_kind=source_kind,
                document_id=document_id,
            )

        logger.info(f"文本摄取完成 (source_kind='{source_kind}')。")

        return {
            "success": True,
            "chunk_count": chunk_info["chunk_count"],
            "node_ids": chunk_info["node_ids"],
            "ref_doc_ids": list({node.ref_doc_id for node in all_nodes if node.ref_doc_id}),
        }
    except Exception as e:
        logger.error(f"文本摄取失败: {e}")
        raise
