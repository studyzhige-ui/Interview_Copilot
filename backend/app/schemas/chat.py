"""Pydantic schemas for chat / mock-interview HTTP endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

# ── Generic chat session DTOs ────────────────────────────────────────────


class SessionCreateRequest(BaseModel):
    # general | debrief (mock_interview sessions are created by the
    # mock-interview start endpoint, never here).
    type: Literal["general", "debrief"] = "general"
    # The interview_record this conversation is about (required for debrief).
    # Bound as subject_type="interview_record", subject_id=<this>.
    subject_id: str | None = Field(default=None, max_length=128)
    title: str | None = Field(default=None, max_length=120)


class SessionCreateResponse(BaseModel):
    session_id: str
    title: str
    type: str


class SessionListItem(BaseModel):
    session_id: str
    title: str
    type: str
    # Persisted run mode (chat|agent) — seeds the FE's CHAT/AGENT pill
    # across devices (AGT-4).
    mode: str = "chat"
    state_summary: str
    turn_count: int
    updated_at: str


class ChatTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    # Execution strategy. ``chat`` runs the L1 chat pipeline (planner →
    # answer LLM, no tool use). ``agent`` runs the L2 ReAct loop with the
    # full tool registry. ``None`` = use the conversation's persisted mode
    # (AGT-4: conversations.mode is authoritative — a device without the
    # localStorage entry no longer silently falls back to chat). An
    # explicit value updates the stored mode. Never agent for
    # mock_interview conversations.
    mode: Literal["chat", "agent"] | None = Field(default=None)


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class MemoryRecallToggleBody(BaseModel):
    enabled: bool


# ── Mock-interview DTOs ──────────────────────────────────────────────────
# Target architecture (RFC §6.4): the start endpoint owns creation of the
# interview_record + conversation + mock_interview_runtime; subsequent calls
# address the run by ``record_id``. No "Runtime Director" — the next
# interviewer line is generated from plan_json + current stage + message
# history. Mirrored 1:1 by the TS interfaces in frontend/src/types/api.ts.


class MockStage(BaseModel):
    """One stage of the (frozen) interview plan, for the progress UI."""

    key: str
    title: str


class MockStartRequest(BaseModel):
    # Personal resume entity (resumes.id) OR a freshly-uploaded resume file
    # asset (file_assets.id). Both optional; at most one is used.
    resume_id: str | None = None
    resume_file_asset_id: str | None = None
    # JD as pasted/parsed text OR an uploaded JD file asset.
    jd_text: str | None = None
    jd_file_asset_id: str | None = None
    # Frozen plan template for this run (phase-1: only "general").
    plan_template_key: str = "general"
    # Interviewer persona for tone. Depth is inferred from JD seniority.
    interviewer_style: str = "professional"  # friendly|professional|rigorous|pressure
    # Interaction mode. 'hybrid' = AI TTS + user types or speaks freely.
    voice_mode: str = "hybrid"  # text|voice|hybrid


class MockStartResp(BaseModel):
    """``POST /mock-interviews/start`` — atomic create + opening line."""

    interview_record_id: str
    conversation_id: str
    runtime_id: str
    current_stage_key: str
    # The opening interviewer message (greeting + first question), one string.
    current_question: str
    # Concurrency token for the first answer (MOCK-3).
    question_message_id: int | None = None
    plan_phases: list[MockStage]


class MockAnswerRequest(BaseModel):
    answer_text: str
    # Optional voice answer clip (file_assets.id, purpose="mock_audio_clip").
    answer_audio_file_asset_id: str | None = None
    # Optimistic concurrency token (MOCK-3): the id of the interviewer
    # message this answer responds to. Mismatch → 409 (a concurrent submit
    # already advanced the interview).
    question_message_id: int


class MockAnswerResp(BaseModel):
    """``POST /mock-interviews/{record_id}/answer`` — next interviewer line."""

    interviewer_message: str
    current_stage_key: str
    # Advisory ONLY (MOCK-5): the FE shows a "可以结束了" suggestion banner;
    # it must never lock the composer. Forced true by the rules layer once
    # MOCK_MAX_ANSWERED_TURNS is reached.
    is_ready_to_finish: bool
    # Echo back with the next answer as the concurrency token (MOCK-3).
    question_message_id: int | None = None


class MockFinishResp(BaseModel):
    """``POST /mock-interviews/{record_id}/finish`` — enter review."""

    status: Literal["processing_review"]
    record_id: str


class MockRetryReviewResp(BaseModel):
    """``POST /mock-interviews/{record_id}/retry-review``."""

    status: Literal["processing_review"]
    record_id: str


class MockAbandonResp(BaseModel):
    """``DELETE /mock-interviews/{record_id}`` — abandon an unfinished run."""

    status: Literal["deleted"]
    record_id: str


class MockInProgressResp(BaseModel):
    """``GET /mock-interviews/in-progress`` — resume banner.

    Discriminated by ``has_in_progress``: when False all other fields are
    None. Sourced from the user's most recent in_progress
    ``mock_interview_runtime`` row.
    """

    has_in_progress: bool
    record_id: str | None = None
    conversation_id: str | None = None
    runtime_id: str | None = None
    title: str | None = None
    current_stage_key: str | None = None
    # The last interviewer line (what the candidate is answering) — lets the
    # frontend re-seed the live view on resume without a history round-trip.
    current_question: str | None = None
    # Answered-turn count so the resumed view doesn't think answeredCount=0
    # (which used to grey out the "生成复盘" button until one more answer).
    answered_count: int = 0
    # Concurrency token for the next answer after resume (MOCK-3).
    question_message_id: int | None = None
    last_activity_at: str | None = None


class MockParseJdResp(BaseModel):
    """``POST /mock-interviews/parse-jd``."""

    text: str
    filename: str | None = None
    chars: int


class MockTranscribeResp(BaseModel):
    """``POST /mock-interviews/transcribe``."""

    text: str
    language: str
    duration_sec: float


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


__all__ = [
    # Generic chat session DTOs
    "SessionCreateRequest",
    "SessionCreateResponse",
    "SessionListItem",
    "ChatTurnRequest",
    "SessionRenameRequest",
    "MemoryRecallToggleBody",
    # Mock-interview DTOs (mirrored 1:1 by frontend/src/types/api.ts)
    "MockStage",
    "MockStartRequest",
    "MockStartResp",
    "MockAnswerRequest",
    "MockAnswerResp",
    "MockFinishResp",
    "MockRetryReviewResp",
    "MockAbandonResp",
    "MockInProgressResp",
    "MockParseJdResp",
    "MockTranscribeResp",
    "TTSRequest",
]
