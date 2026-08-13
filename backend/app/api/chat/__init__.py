"""Chat API package — assembles all chat session routers under one mount point.

Submodules:
  - sessions       : session CRUD + full transcript
  - streaming      : SSE QA streaming

Legacy cross-session Memory CRUD is intentionally not mounted. Stage 0 keeps
the mixed store out of runtime Context/Recall until canonical owners exist.

The package mounts every submodule's router into a single ``router`` so
that ``app.main`` can keep its existing one-line include:
    app.include_router(chat.router, prefix="/api/v1")

"""

from fastapi import APIRouter

from app.api.chat import client_actions, sessions, streaming

router = APIRouter()
router.include_router(client_actions.router)
router.include_router(sessions.router)
router.include_router(streaming.router)


__all__ = ["router"]
