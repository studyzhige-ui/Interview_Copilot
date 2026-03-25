import logging
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.agent.agent_executor import chat_with_agent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])

class ChatRequest(BaseModel):
    message: str = Field(..., description="用户发给 面试 Copilot Agent 的自然语言信息")

@router.post("/agent/chat")
async def api_agent_chat(request: ChatRequest):
    """
    Agent RAG 对话综合大类网关入口。自动动态调配后端知识库。
    """
    try:
        reply = await chat_with_agent(request.message)
        
        return {
            "status": "success",
            "reply": reply
        }
    except Exception as e:
        logger.error(f"Agent 路由调用阻断: {e}")
        raise HTTPException(status_code=500, detail=str(e))
