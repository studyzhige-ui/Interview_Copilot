import logging

from app.rag.retriever import query_knowledge_base

logger = logging.getLogger(__name__)


async def search_interview_qa(query: str, user_id: str = "") -> str:
    """Search interview question-and-answer knowledge."""
    logger.info("Calling RAG search for source_type=interview_qa")
    result = await query_knowledge_base(query, user_id=user_id, source_type="interview_qa")
    return result["answer"]


async def search_official_docs(query: str, user_id: str = "") -> str:
    """Search official technical documentation."""
    logger.info("Calling RAG search for source_type=official_docs")
    result = await query_knowledge_base(query, user_id=user_id, source_type="official_docs")
    return result["answer"]


async def search_personal_memory(query: str, user_id: str = "") -> str:
    """Search a user's private interview history and memory."""
    logger.info("Calling RAG search for source_type=personal_memory")
    result = await query_knowledge_base(query, user_id=user_id, source_type="personal_memory")
    return result["answer"]
