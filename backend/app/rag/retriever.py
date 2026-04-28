import os
import logging
from typing import Optional, Dict, Any

from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.core.vector_stores import MetadataFilters, MetadataFilter, FilterOperator
from llama_index.core.retrievers import VectorIndexRetriever

# 解决跨版本 LlamaIndex-Core 与 BM25 强绑定函数被移除的 Import Bug
import llama_index.core.vector_stores.utils
if not hasattr(llama_index.core.vector_stores.utils, "build_metadata_filter_fn"):
    def _mock_build_metadata_filter_fn(*args, **kwargs):
        return lambda x: True
    llama_index.core.vector_stores.utils.build_metadata_filter_fn = _mock_build_metadata_filter_fn

from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank
from llama_index.storage.docstore.postgres import PostgresDocumentStore

from app.core.config import settings
from app.core.hf_runtime import prepare_hf_runtime, resolve_local_snapshot
from app.rag.embeddings import init_rag_settings

logger = logging.getLogger(__name__)

# 大模型架构与驱动点确认挂载生效
init_rag_settings()

MILVUS_URI = settings.MILVUS_URI
MILVUS_COLLECTION = settings.MILVUS_COLLECTION

# bge-small-zh-v1.5 输出维度
EMBEDDING_DIM = 512

reranker = None


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


def init_reranker():
    global reranker
    if reranker is not None:
        return
    try:
        prepare_hf_runtime()
        reranker_model = resolve_local_snapshot(settings.RERANKER_MODEL_ID)
        if reranker_model is None:
            raise RuntimeError(
                f"Reranker model '{settings.RERANKER_MODEL_ID}' is missing. "
                "Run the model init script before starting the backend."
            )
        reranker = SentenceTransformerRerank(
            model=reranker_model,
            top_n=settings.RERANK_TOP_N,
        )
        logger.info("BGE-Reranker 交叉注意力模型加载完成。")
    except Exception as e:
        logger.error(f"BGE-Reranker 启动失败: {e}")
        raise


async def query_knowledge_base(
    query_str: str,
    user_id: str,
    source_type: Optional[str] = None,
    min_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    混合检索中枢（向量 + BM25 + Reranker + 防幻觉拦截）。

    P0 安全：严格通过 MetadataFilter 隔离 user_id。
    防幻觉：使用 Reranker 绝对置信分数截断低质量节点。
    """
    try:
        if min_score is None:
            min_score = settings.RAG_MIN_SCORE

        # ===== [1] 连接 Milvus 向量引擎 =====
        vector_store = MilvusVectorStore(
            uri=MILVUS_URI,
            collection_name=MILVUS_COLLECTION,
            dim=EMBEDDING_DIM,
            overwrite=False,
            similarity_metric=settings.MILVUS_SIMILARITY_METRIC,
            index_config=_milvus_dense_index_config(),
            search_config=_milvus_search_config(),
        )
        logger.info(
            "Milvus dense index config active: index_type=%s, metric=%s, M=%s, efConstruction=%s, efSearch=%s",
            settings.MILVUS_DENSE_INDEX_TYPE,
            settings.MILVUS_SIMILARITY_METRIC,
            settings.MILVUS_HNSW_M,
            settings.MILVUS_HNSW_EF_CONSTRUCTION,
            settings.MILVUS_HNSW_EF_SEARCH,
        )
        index = VectorStoreIndex.from_vector_store(vector_store)

        # ===== [2] 构建多租户隔离过滤器 (Milvus MetadataFilter) =====
        filter_list = [
            MetadataFilter(key="user_id", value=user_id, operator=FilterOperator.EQ)
        ]
        if source_type:
            filter_list.append(
                MetadataFilter(key="source_type", value=source_type, operator=FilterOperator.EQ)
            )

        filters = MetadataFilters(filters=filter_list, condition="and")
        logger.info(f"元数据过滤器已激活: user_id={user_id}, source_type={source_type}")

        # 向量检索器
        vector_retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=settings.VECTOR_TOP_K,
            filters=filters
        )

        # ===== [3] BM25 检索器构建 =====
        final_retriever = vector_retriever

        try:
            docstore = PostgresDocumentStore.from_uri(uri=settings.DATABASE_URL)
            # docstore.docs 内部结构返回是一个包含 Document/Node 的字典
            all_nodes = list(docstore.docs.values())

            if all_nodes:
                # Python 层面精确过滤（BM25 不支持原生 metadata 过滤）
                filtered_nodes = [n for n in all_nodes if n.metadata.get("user_id") == user_id]

                if source_type:
                    filtered_nodes = [n for n in filtered_nodes if n.metadata.get("source_type") == source_type]

                if len(filtered_nodes) > 0:
                    bm25_retriever = BM25Retriever.from_defaults(
                        nodes=filtered_nodes,
                        similarity_top_k=settings.BM25_TOP_K,
                    )

                    # RRF 融合检索
                    final_retriever = QueryFusionRetriever(
                        retrievers=[vector_retriever, bm25_retriever],
                        similarity_top_k=settings.FUSION_TOP_K,
                        num_queries=1,
                        mode="reciprocal_rerank"
                    )
                    logger.info(f"BM25 + 向量混合检索启动，节点池: {len(filtered_nodes)} 个")
                else:
                    logger.warning("目标隔离区域下节点为空，仅使用向量检索。")
            else:
                logger.warning("Postgres Docstore 无节点记录，仅使用向量检索。")
        except Exception as e_bm25:
            logger.warning(f"BM25 构建失败，降级为纯向量检索: {e_bm25}")

        # ===== [4] 检索 + Rerank + 防幻觉拦截 =====
        logger.info(f"开始检索: {query_str}")

        try:
            from llama_index.core import QueryBundle
            query_bundle = QueryBundle(query_str)
            raw_nodes = await final_retriever.aretrieve(query_str)
        except Exception as ret_e:
            logger.error(f"节点召回失败: {ret_e}")
            raw_nodes = []

        # Reranker 交叉注意力重排序
        if reranker and raw_nodes:
            processed_nodes = reranker.postprocess_nodes(raw_nodes, query_bundle)
        else:
            processed_nodes = raw_nodes

        # 绝对分数阈值拦截
        valid_nodes = [
            node for node in processed_nodes
            if node.score is not None and node.score >= min_score
        ]
        valid_nodes = valid_nodes[:settings.RERANK_TOP_N]

        if not valid_nodes:
            logger.warning(f"防幻觉拦截触发：所有节点得分低于阈值 ({min_score})")
            return {
                "answer": "[SYSTEM_EMPTY_WARNING] 知识库中未检索到与该问题高度相关的参考信息。",
                "sources": []
            }

        logger.info(f"通过阈值过滤: {len(valid_nodes)} 个节点 (阈值={min_score})")

        # ===== [5] 封装结果 =====
        sources = []
        texts = []
        for n in valid_nodes:
            score = float(n.score) if n.score is not None else 0.0
            content = n.node.get_content().strip()
            texts.append(f"[Reranker Score: {score:.3f}] {content}")
            sources.append({
                "score": score,
                "text": content,
                "metadata": n.node.metadata
            })

        return {
            "answer": "\n\n".join(texts),
            "sources": sources
        }

    except Exception as e:
        logger.error(f"检索引擎异常: {e}")
        raise
