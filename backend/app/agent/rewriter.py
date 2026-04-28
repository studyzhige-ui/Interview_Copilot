import logging
from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)

async def rewrite_query(user_message: str, chat_context: str) -> str:
    """
    独立查询重构引擎 (Standalone Query Rewriter Node)。
    专门负责解决多轮 RAG 对话中典型的指代不明（“那这个呢？”、“上一题为什么”）问题。
    将含糊不清的用户句子，利用高速专线模型补全为可以直接喂给 Router 和检索器的全维实体句子。
    """
    if not chat_context.strip():
        # 冷启动状态下，无需做指代消解补全，原样通过
        return user_message

    prompt = f"""
【核心指令】：
你是一个自然语言指代消解与补全处理器。
以下是用户的当前提问，以及该用户和系统之间的多轮对话上下文（包含摘要和近期的聊天记录）。
请你仅做一件事：判断【当前用户问题】是否依赖上下文才能被理解（如出现“它”、“刚才提到的那个”、“这个底层机制”等指代不明或省略语境的话术）。
- 如果依赖，请基于上下文，把用户的话**补充成一句完全独立、技术语义完整、毫无指代词**的技术询问句，用于后续独立投喂给搜索引擎。
- 如果用户的问题本身已经很完整清晰，或者与上下文毫无关联属于开启新话题，请**原封不动地返回用户的原话**。

【绝对禁令】：
严禁回答用户的问题！严禁输出类似“好的，改写如下”、“用户的原意是”等任何解释性废话！你只能输出改写后的句子本身或者原句，且不需要打引号！

【多轮对话上下文】：
{chat_context}

【当前用户问题】：
{user_message}
"""
    try:
        response = await agent_fast_llm.acomplete(prompt)
        rewritten_text = str(response.text).strip()

        if rewritten_text != user_message:
            logger.info(f"Query Rewrite (指代补全消除黑盒): '{user_message}' => '{rewritten_text}'")

        return rewritten_text
    except Exception as e:
        logger.error(f"引擎重组重写管道阻塞，直接放行原意: {e}")
        return user_message
