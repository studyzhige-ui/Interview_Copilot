import logging
from llama_index.core.agent import ReActAgent
from llama_index.core import Settings
from app.agent.tools import agent_tools
from app.rag.embeddings import init_rag_settings

logger = logging.getLogger(__name__)

def get_agent() -> ReActAgent:
    """
    配置并加载 DeepSeek ReAct 代理。
    新版核心架构中的 Agent 是基类为 BaseWorkflowAgent 的工作流，
    通过标准初始化而非 from_tools。
    """
    agent = ReActAgent(
        name="Interview_Copilot_Agent",
        description="全能面试辅助智能体",
        tools=agent_tools,
        llm=Settings.llm,
        verbose=True
    )
    return agent

async def chat_with_agent(user_message: str) -> str:
    """
    代理核心流入口：提供自然语言请求，执行异步思考返回。
    """
    try:
        agent = get_agent()
        
        logger.info(f"Agent 收到了新的用户委托指令: {user_message}")
        
        # 新版使用 run 工作流接口，最新版本要求传入 user_msg 或 chat_history
        response = await agent.run(user_msg=user_message)
        
        # 兼容最新版输出 AgentOutput
        if hasattr(response, "response"):
            return str(response.response)
        return str(response)
    except Exception as e:
        import traceback
        logger.error(f"Agent 执行链路发生致命断层: {e}\n{traceback.format_exc()}")
        return f"Agent 内部逻辑异常：{e}"
