"""Pydantic schemas for chat / mock-interview HTTP endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


# ── Mock-interview Director action enum ──────────────────────────────────
# Must match the seven keys in
# ``app/services/mock_interview_service.py:DISPLAY_INTENT``. Mirrored 1:1 by
# the frontend ``MockDirectorAction`` union in
# ``frontend/src/types/api.ts``. Adding a new action requires updating all
# three sites — the Literal here will refuse new strings at response time so
# the BE can't silently emit an action the FE doesn't render.
MockDirectorAction = Literal[
    "follow_up",
    "new_question",
    "transition",
    "hint",
    "clarify",
    "reverse_answer",
    "finish",
]


class MockPhaseProgress(BaseModel):
    """v6 phase progress — populated on every Director turn (no Optional)."""
    current_phase: str
    turn_count: int
    max_turns: int
    follow_up_depth: int


class MockFinishResp(BaseModel):
    """Wire-format response for ``POST /chat/mock-interview/finish``.

    Mirrored 1:1 by ``MockFinishResp`` in ``frontend/src/types/api.ts``.
    """
    status: Literal["analyzing"]
    record_id: str
    debrief_session_id: str
    task_id: str


class MockAbandonResp(BaseModel):
    """Wire-format response for ``POST /chat/mock-interview/abandon``."""
    status: Literal["deleted"]
    session_id: str


class MockAnswerResp(BaseModel):
    """Wire-format response for ``POST /chat/mock-interview/answer``.

    Mirrored 1:1 by ``MockAnswerResp`` in ``frontend/src/types/api.ts``.
    The TS type is hand-written, so renaming a field here without
    updating it ships a runtime bug that typecheck cannot catch. The
    cross-cutting fix would be an openapi-generated TS client; until
    that lands, treat both files as the contract.
    """
    interviewer_response: str
    spoken_response: str
    next_question: str
    action: MockDirectorAction
    display_intent: str
    is_finished: bool
    phase_progress: MockPhaseProgress


class SessionCreateRequest(BaseModel):
    session_type: str = "general"  # "general" | "debrief" | "mock_interview"
    interview_id: str | None = None
    title: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    title: str
    session_type: str


class SessionListItem(BaseModel):
    session_id: str
    title: str
    session_type: str
    state_summary: str
    turn_count: int
    updated_at: str


class MessageItem(BaseModel):
    seq: int
    role: str
    content: str
    created_at: str


class SSEChatRequest(BaseModel):
    message: str
    # Execution strategy. ``chat`` runs the L1 chat pipeline (planner →
    # answer LLM, no tool use). ``agent`` runs the L2 ReAct loop with
    # the full tool registry (search_jobs, web_search, read_url,
    # search_knowledge, read_resume, read_interview_history, read_file,
    # write_file, recall_memory, save_memory).
    #
    # Default ``chat`` for back-compat: any pre-existing client that
    # doesn't send the field continues to land on the chat path. The
    # frontend's AGENT pill MUST pass ``"agent"`` here — without that
    # plumbing the tool registry never reaches the LLM and "AGENT mode"
    # is purely decorative.
    mode: Literal["chat", "agent"] = Field(default="chat")


class MockStartRequest(BaseModel):
    session_id: str
    resume_upload_id: str | None = None
    jd_upload_id: str | None = None
    # User-pasted JD text. Wins over jd_upload_id if both present.
    jd_text: str | None = None
    # Interviewer persona for tone. Depth is inferred from JD seniority.
    interviewer_style: str = "professional"   # friendly|professional|rigorous|pressure
    # Interaction mode. 'hybrid' = AI TTS + user types or speaks freely.
    voice_mode: str = "hybrid"                # text|voice|hybrid


class SessionRenameRequest(BaseModel):
    title: str


class MockAnswerRequest(BaseModel):
    session_id: str
    answer: str


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


__all__ = [
    "SessionCreateRequest",
    "SessionCreateResponse",
    "SessionListItem",
    "MessageItem",
    "SSEChatRequest",
    "MockStartRequest",
    "MockAnswerRequest",
    "SessionRenameRequest",
    "TTSRequest",
]
