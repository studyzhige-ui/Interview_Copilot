"""Chat API package — assembles all chat-related routers under one mount point.

Submodules:
  - sessions       : session CRUD + full transcript
  - memory_items   : memory-item CRUD
  - streaming      : WebSocket + SSE QA streaming
  - mock_interview : mock interview control + TTS

The package mounts every submodule's router into a single ``router`` so
that ``app.main`` can keep its existing one-line include:
    app.include_router(chat.router, prefix="/api/v1")

For monkeypatch back-compat with the pre-split single-file module, we
also expose ``transcript_service`` at the package level — older tests
patched ``app.api.chat.transcript_service`` and that name keeps working,
but new tests should patch the specific submodule
(``app.api.chat.sessions.transcript_service`` etc.).
"""

from fastapi import APIRouter

from app.api.chat import memory_items, mock_interview, sessions, streaming
from app.services.chat.chat_history_service import transcript_service  # noqa: F401

router = APIRouter()
router.include_router(sessions.router)
router.include_router(memory_items.router)
router.include_router(streaming.router)
router.include_router(mock_interview.router)


__all__ = ["router", "transcript_service"]
