"""Chat API package — assembles all chat session routers under one mount point.

Submodules:
  - sessions       : session CRUD + full transcript
  - streaming      : SSE QA streaming
  - mock_interview : mock interview control + TTS

Memory CRUD endpoints used to live here as ``chat/memory.py`` but were
moved out in P8-1 — they manage cross-session memory docs (knowledge /
strategy / habit / user_profile), not chat-session operations.
See ``app.api.memory`` for the new home.

The package mounts every submodule's router into a single ``router`` so
that ``app.main`` can keep its existing one-line include:
    app.include_router(chat.router, prefix="/api/v1")

"""

from fastapi import APIRouter

from app.api.chat import mock_interview, sessions, streaming

router = APIRouter()
router.include_router(sessions.router)
router.include_router(streaming.router)
router.include_router(mock_interview.router)


__all__ = ["router"]
