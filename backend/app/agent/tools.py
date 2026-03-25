import logging
from llama_index.core.tools import FunctionTool
from app.rag.retriever import query_knowledge_base

logger = logging.getLogger(__name__)

async def search_technical_knowledge(query: str) -> str:
    """搜技术面库入口"""
    logger.info(f"Agent 调用技术领域工具：{query}")
    result = await query_knowledge_base(query, source_type="interview_qa")
    return result["answer"]

async def search_personal_memory(query: str) -> str:
    """搜私有面录入口"""
    logger.info(f"Agent 调用私人回忆工具：{query}")
    result = await query_knowledge_base(query, source_type="personal_memory")
    return result["answer"]

# 通过名字和精确的描述向 Agent 大脑展示这两个工具分别能解决什么问题
technical_tool = FunctionTool.from_defaults(
    name="search_technical_knowledge",
    async_fn=search_technical_knowledge,
    description="用于搜索和解答标准的面试题、框架原理（例：Java, Redis, MySQL, 微服务架构等知识）。若用户向你探讨纯粹的技术底层原理或标准问答，请第一时间抽取核心词调用此工具。"
)

personal_tool = FunctionTool.from_defaults(
    name="search_personal_memory",
    async_fn=search_personal_memory,
    description="专门用于查询用户自己过去的真实面试记录、历史评分、缺点暴露、表现建议等。如果用户聊到自身的过往、被挑刺的点、“我上次的面试”、“针对我的建议”，请果断使用此工具。"
)

# 聚合抛出
agent_tools = [technical_tool, personal_tool]
