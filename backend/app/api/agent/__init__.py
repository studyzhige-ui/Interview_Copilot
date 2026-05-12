"""Agent API package — mounts all agent-related routers.

Submodules:
  - chat_compat  : ``/agent/chat`` (legacy QA-pipeline compatibility)
  - react_agent  : ``/agent/react/chat`` and ``/agent/react/stream``
  - runs         : ``/agent/runs``, ``/agent/runs/{id}``, ``/agent/metrics``
"""

from fastapi import APIRouter

from app.api.agent import chat_compat, react_agent, runs

router = APIRouter()
router.include_router(chat_compat.router)
router.include_router(react_agent.router)
router.include_router(runs.router)


__all__ = ["router"]
