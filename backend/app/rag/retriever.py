import os
import logging
import chromadb
from typing import Optional, Dict, Any

from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
from app.rag.embeddings import init_rag_settings

logger = logging.getLogger(__name__)

# 确保底层设定（包括刚刚加入的硬件加速、大模型指针）已全局加载
init_rag_settings()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROMA_DB_DIR = os.path.join(BASE_DIR, "data", "chroma_db")

async def query_knowledge_base(query_str: str, source_type: Optional[str] = None) -> Dict[str, Any]:
    """
    向 RAG 知识库系统提问的异步入口。
    
    参数:
        query_str (str): 用户输入的问题
        source_type (str, optional): 需要精确匹配的知识库域。为空则进行全库混搜。
        
    返回:
        Dict: 包含了 DeepSeek 总结回复，和溯源的源文档切分节点。
    """
    try:
        # 检查向量数据库物理文件夹是否存在
        if not os.path.exists(CHROMA_DB_DIR):
            logger.warning("未寻址到 Chroma 数据库，可能库为空。")
            return {"answer": "本地知识库为空，尚未摄取数据。", "sources": []}
            
        # 绑定持久化的本地 ChromaDB 服务
        db = chromadb.PersistentClient(path=CHROMA_DB_DIR)
        
        try:
            # 读取 collection 名，必须在建立 ingest 的时候定好
            chroma_collection = db.get_collection("interview_copilot_rag")
        except ValueError:
             # Chroma 内部找不到相关 collection 时引发
             return {"answer": "当前无对应名称的数据集。", "sources": []}
             
        # LlamaIndex 的桥接
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        index = VectorStoreIndex.from_vector_store(vector_store)
        
        # 核心：根据不同 Agent 的需求构建路由拦截过滤器
        filters = None
        if source_type:
            filters = MetadataFilters(
                filters=[ExactMatchFilter(key="source_type", value=source_type)]
            )
            logger.info(f"启用数据隔离防护引擎，严格通过源 {source_type} 回答查源。")
            
        query_engine = index.as_query_engine(
            similarity_top_k=3,
            filters=filters
        )
        
        logger.info(f"触发查询，Prompt：{query_str}")
        response = await query_engine.aquery(query_str)
        
        # 规整出处
        sources = []
        if response.source_nodes:
            for node in response.source_nodes:
                sources.append({
                    "score": node.score,
                    "text": node.node.get_content().strip(),
                    "metadata": node.node.metadata
                })
                
        return {
            "answer": str(response),
            "sources": sources
        }
        
    except Exception as e:
        logger.error(f"知识库检索查询期执行错误: {e}")
        raise
