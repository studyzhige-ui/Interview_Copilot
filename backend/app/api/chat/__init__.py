"""Chat API package — assembles all chat-related routers under one mount point.

Submodules:
  - sessions       : session CRUD + full transcript
  - memory         : v3 memory CRUD (knowledge / strategy / habit /
                     user_profile docs + audit log). The file was
                     historically named ``memory_items.py`` (back when
                     v2 memory was a flat row-per-item table) — renamed
                     in the audit cleanup so a grep for "where are the
                     memory endpoints" actually lands here.
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

from app.api.chat import memory, mock_interview, sessions, streaming
from app.services.chat.chat_history_service import transcript_service  # noqa: F401

router = APIRouter()
router.include_router(sessions.router)
router.include_router(memory.router)
router.include_router(streaming.router)
router.include_router(mock_interview.router)


__all__ = ["router", "transcript_service"]
