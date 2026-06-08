import os
import logging
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

logger = logging.getLogger(__name__)




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


def _write_to_milvus_hybrid(
    all_nodes: list, *, user_id: int, source_kind: str, document_id: str | None,
) -> None:
    """Embed each node (dense) and insert into the Milvus 2.6 hybrid collection.

    The sparse/BM25 vector is computed server-side from ``text`` by the
    collection's BM25 ``Function`` — we only supply the dense vector + text +
    scope fields (``user_id`` is the stable users.id pk). Re-ingesting a document
    replaces its prior chunks first.
    """
    from app.rag import milvus_hybrid

    texts = [_node_text(n) for n in all_nodes]
    embeddings = Settings.embed_model.get_text_embedding_batch(texts, show_progress=True)
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
        milvus_hybrid.delete_by_document(document_id)
    milvus_hybrid.insert(rows)


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

    # Tabular files (CSV / XLSX): split by row groups and repeat the header in
    # every chunk so a retrieved chunk is independently understandable.
    if file_name.endswith((".csv", ".tsv", ".xlsx", ".xls")):
        nodes = _table_aware_nodes(document, CHUNK_SIZE * 2)
    else:
        if (
            is_markdown_parsed
            or file_name.endswith((".md", ".markdown"))
            or source_kind in ["interview_qa", "official_docs"]
        ):
            parser = MarkdownNodeParser()
        elif file_name.endswith((".html", ".htm")):
            # HTML-aware: keeps heading/section/list/table/code structure,
            # drops script/style/nav noise.
            parser = HTMLNodeParser()
        elif file_name.endswith(".json"):
            parser = JSONNodeParser()
        elif file_name.endswith(".py"):
            parser = CodeSplitter(language="python", chunk_lines=40, chunk_lines_overlap=5)
        elif file_name.endswith(".java"):
            parser = CodeSplitter(language="java", chunk_lines=40, chunk_lines_overlap=5)
        elif file_name.endswith(".cpp") or file_name.endswith(".c"):
            parser = CodeSplitter(language="cpp", chunk_lines=40, chunk_lines_overlap=5)
        else:
            parser = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

        nodes = parser.get_nodes_from_documents([document])

    # 二次兜底：对超长 chunk 做再切分，确保不超过 embedding 模型 max_seq_length
    secondary_splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    final_nodes = []
    for node in nodes:
        text = node.get_content()
        # 粗略估算：1 个中文字符 ≈ 1.5 tokens，1 英文单词 ≈ 1.3 tokens
        estimated_tokens = len(text)  # 按字符数做保守估计
        if estimated_tokens > CHUNK_SIZE * 2:
            sub_nodes = secondary_splitter.get_nodes_from_documents(
                [Document(text=text, metadata=node.metadata)]
            )
            final_nodes.extend(sub_nodes)
        else:
            final_nodes.append(node)

    # P0 级红线：阻止 NodeParser 洗掉原文档的 Metadata
    user_id = document.metadata.get("user_id", "")
    for node in final_nodes:
        node.metadata["source_kind"] = source_kind
        if user_id:
            node.metadata["user_id"] = user_id

    return final_nodes


async def ingest_document(
    file_path: str,
    source_kind: str,
    user_id: int,
    *,
    document_id: str | None = None,
    upload_id: str | None = None,
    category: str | None = None,
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
            if category:
                doc.metadata["category"] = category

            if _has_llama_cloud and doc.metadata.get("file_name", "").endswith((".pdf", ".pptx", ".docx")):
                doc.metadata["is_markdown_parsed"] = True

        # 自适应切块
        all_nodes = []
        for doc in documents:
            nodes = get_optimal_nodes(doc)
            all_nodes.extend(nodes)

        for node in all_nodes:
            if document_id:
                node.metadata["document_id"] = document_id
            if upload_id:
                node.metadata["upload_id"] = upload_id
            if category:
                node.metadata["category"] = category

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
                metadata={"category": category} if category else None,
            )

        logger.info(f">>> 摄取完成: '{file_path}' (source_kind={source_kind}, user_id={user_id})")

        return {
            "success": True,
            "chunk_count": chunk_info["chunk_count"],
            "node_ids": chunk_info["node_ids"],
            "ref_doc_ids": list({node.ref_doc_id for node in all_nodes if node.ref_doc_id}),
        }

    except Exception as e:
        logger.error(f"文档摄取失败: {e}")
        raise


async def ingest_text(text: str, source_kind: str, user_id: int, metadata: dict = None):
    """
    纯文本节点摄取通道。
    P0 安全：强制执行多租户隔离。
    """
    try:
        final_metadata = metadata or {}
        final_metadata["source_kind"] = source_kind
        final_metadata["user_id"] = user_id

        doc = Document(text=text, metadata=final_metadata)
        all_nodes = get_optimal_nodes(doc)

        logger.info(f"纯文本摄取: {len(all_nodes)} 个节点写入 Milvus hybrid...")
        _write_to_milvus_hybrid(
            all_nodes, user_id=user_id, source_kind=source_kind, document_id=None,
        )

        # Persist to document_chunks (document_id NULL — e.g. personal_memory),
        # so the diagnostics report reads from Postgres, not a docstore.
        from app.db.database import SessionLocal
        from app.services.knowledge.document_chunk_service import write_chunks
        with SessionLocal() as db:
            chunk_info = write_chunks(
                db, nodes=all_nodes, user_id=user_id, source_kind=source_kind,
                document_id=None, metadata=metadata or None,
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
