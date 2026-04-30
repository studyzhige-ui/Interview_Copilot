import os
import logging
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Document
from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.readers.file import PyMuPDFReader
from llama_index.storage.docstore.postgres import PostgresDocumentStore
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter, JSONNodeParser, CodeSplitter
from app.rag.embeddings import init_rag_settings
from app.core.config import settings

logger = logging.getLogger(__name__)

# 确保底层大模型设定生效
init_rag_settings()

MILVUS_URI = settings.MILVUS_URI
MILVUS_COLLECTION = settings.MILVUS_COLLECTION

# bge-small-zh-v1.5 输出维度 = 512
EMBEDDING_DIM = 512


def _milvus_dense_index_config() -> dict:
    return {
        "index_type": settings.MILVUS_DENSE_INDEX_TYPE,
        "metric_type": settings.MILVUS_SIMILARITY_METRIC,
        "M": settings.MILVUS_HNSW_M,
        "efConstruction": settings.MILVUS_HNSW_EF_CONSTRUCTION,
    }


def _milvus_search_config() -> dict:
    return {
        "metric_type": settings.MILVUS_SIMILARITY_METRIC,
        "params": {
            "ef": settings.MILVUS_HNSW_EF_SEARCH,
        },
    }


def get_optimal_nodes(document: Document) -> list:
    """
    自适应切块引擎：基于文档类型和内容结构智能选择切分策略。
    """
    source_type = document.metadata.get("source_type", "")
    file_name = document.metadata.get("file_name", "").lower()

    is_markdown_parsed = document.metadata.get("is_markdown_parsed", False)

    if is_markdown_parsed or file_name.endswith(".md") or file_name.endswith(".markdown") or source_type in ["interview_qa", "official_docs"]:
        parser = MarkdownNodeParser()
    elif file_name.endswith(".json"):
        parser = JSONNodeParser()
    elif file_name.endswith(".py"):
        parser = CodeSplitter(language="python")
    elif file_name.endswith(".java"):
        parser = CodeSplitter(language="java")
    elif file_name.endswith(".cpp") or file_name.endswith(".c"):
        parser = CodeSplitter(language="cpp")
    else:
        parser = SentenceSplitter(chunk_size=1024, chunk_overlap=100)

    nodes = parser.get_nodes_from_documents([document])

    # P0 级红线：阻止 NodeParser 洗掉原文档的 Metadata
    user_id = document.metadata.get("user_id", "")
    for node in nodes:
        node.metadata["source_type"] = source_type
        if user_id:
            node.metadata["user_id"] = user_id

    return nodes


def _get_milvus_vector_store(overwrite: bool = False) -> MilvusVectorStore:
    """
    创建连接到 Milvus Standalone 的 VectorStore 实例。
    overwrite=True 时会清空并重建 collection。
    """
    return MilvusVectorStore(
        uri=MILVUS_URI,
        collection_name=MILVUS_COLLECTION,
        dim=EMBEDDING_DIM,
        overwrite=overwrite,
        similarity_metric=settings.MILVUS_SIMILARITY_METRIC,
        index_config=_milvus_dense_index_config(),
        search_config=_milvus_search_config(),
    )


def _get_storage_context(vector_store: MilvusVectorStore) -> StorageContext:
    """
    加载全局共享的混合储藏环境。
    通过 PostgreSQL 获取纯天然持久化的 DocumentStore，配合 Milvus 驱动 Reranker 的回溯。
    """
    try:
        docstore = PostgresDocumentStore.from_uri(uri=settings.DATABASE_URL)
        logger.info("已成功挂载基于 PostgreSQL 的 Docstore.")
    except Exception as e:
        logger.error(f"无法衔接 PostgreSQL Docstore: {e}")
        raise

    return StorageContext.from_defaults(
        docstore=docstore,
        vector_store=vector_store
    )


async def ingest_document(
    file_path: str,
    source_type: str,
    user_id: str,
    *,
    document_id: str | None = None,
    upload_id: str | None = None,
    category: str | None = None,
):
    """
    文档摄取入口：解析文件 → 自适应切块 → 写入 Milvus + Docstore。
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
            doc.metadata["source_type"] = source_type
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

        # 连接 Milvus（追加模式，不清空现有数据）
        vector_store = _get_milvus_vector_store(overwrite=False)
        storage_context = _get_storage_context(vector_store)

        logger.info(f">>> 开始写入 Milvus + Docstore，共 {len(all_nodes)} 个节点...")
        index = VectorStoreIndex(
            nodes=all_nodes,
            storage_context=storage_context,
            store_nodes_override=True,
            show_progress=True
        )

        logger.info(f">>> 摄取完成: '{file_path}' (source_type={source_type}, user_id={user_id})")
        return {
            "success": True,
            "chunk_count": len(all_nodes),
            "node_ids": [node.node_id for node in all_nodes],
            "ref_doc_ids": list({node.ref_doc_id for node in all_nodes if node.ref_doc_id}),
        }

    except Exception as e:
        logger.error(f"文档摄取失败: {e}")
        raise


async def ingest_text(text: str, source_type: str, user_id: str, metadata: dict = None):
    """
    纯文本节点摄取通道。
    P0 安全：强制执行多租户隔离。
    """
    try:
        final_metadata = metadata or {}
        final_metadata["source_type"] = source_type
        final_metadata["user_id"] = user_id

        doc = Document(text=text, metadata=final_metadata)
        all_nodes = get_optimal_nodes(doc)

        vector_store = _get_milvus_vector_store(overwrite=False)
        storage_context = _get_storage_context(vector_store)

        logger.info(f"纯文本摄取: {len(all_nodes)} 个节点写入 Milvus...")
        index = VectorStoreIndex(
            nodes=all_nodes,
            storage_context=storage_context,
            store_nodes_override=True
        )

        logger.info(f"文本摄取完成 (source_type='{source_type}')。")
        return {
            "success": True,
            "chunk_count": len(all_nodes),
            "node_ids": [node.node_id for node in all_nodes],
            "ref_doc_ids": list({node.ref_doc_id for node in all_nodes if node.ref_doc_id}),
        }
    except Exception as e:
        logger.error(f"文本摄取失败: {e}")
        raise
