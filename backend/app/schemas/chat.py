"""Pydantic schemas for chat / mock-interview HTTP endpoints."""

from typing import Literal

from pydantic import BaseModel, Field, PositiveInt, field_validator

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
    execution_mode: Literal["standard", "auto"] = "standard"
    execution_mode_version: int = Field(default=0, ge=0)


class SessionListItem(BaseModel):
    session_id: str
    title: str
    type: str
    # Persisted run mode (chat|agent) — seeds the FE's CHAT/AGENT pill
    # across devices (AGT-4).
    mode: str = "chat"
    execution_mode: Literal["standard", "auto"] = "standard"
    execution_mode_version: int = Field(default=0, ge=0)
    state_summary: str
    turn_count: int
    updated_at: str


class AttachmentRef(BaseModel):
    """One durable Composer attachment draft selected for this submission."""

    draft_id: str = Field(min_length=1, max_length=128)


ProductObjectKind = Literal[
    "career_profile",
    "career_profile_direction",
    "job_opportunity",
    "next_action",
    "artifact",
    "interview_record",
]


class ProductObjectReference(BaseModel):
    """A user-submitted product identity, never copied business fields."""

    kind: ProductObjectKind
    object_id: str = Field(min_length=1, max_length=128)

    @field_validator("object_id")
    @classmethod
    def normalize_object_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("object_id cannot be blank")
        return normalized


class ChatTurnRequest(BaseModel):
    # Stable client-generated identity. Retrying the same identity and version
    # is idempotent; reusing it for different input is rejected.
    submission_id: str = Field(min_length=1, max_length=128)
    version: PositiveInt = 1
    message: str = Field(min_length=1, max_length=100_000)
    attachments: list[AttachmentRef] = Field(default_factory=list, max_length=10)
    # Explicit references selected from debrief QA cards. This is execution
    # input for one durable turn, not interview-record data.
    question_indexes: list[PositiveInt] = Field(default_factory=list)
    # Explicit product objects selected through a user-visible handoff. The
    # server trusts only kind + identity and rereads the authoritative owner.
    object_references: list[ProductObjectReference] = Field(
        default_factory=list,
        max_length=8,
    )
    # Execution strategy. ``chat`` runs the L1 chat pipeline (planner →
    # answer LLM, no tool use). ``agent`` runs the L2 ReAct loop with the
    # full tool registry. ``None`` = use the conversation's persisted mode
    # (AGT-4: conversations.mode is authoritative — a device without the
    # localStorage entry no longer silently falls back to chat). An
    # explicit value updates the stored mode. Never agent for
    # mock_interview conversations.
    mode: Literal["chat", "agent"] | None = Field(default=None)
    # Policy mode is separate from Chat/Agent strategy.  Conversation is the
    # authority for every new submission; this optional field remains only for
    # rolling-client wire compatibility and cannot overwrite that setting.
    # Once queued, PendingSubmission owns the editable pre-claim task snapshot.
    execution_mode: Literal["standard", "auto"] | None = None
    source_client_id: str | None = Field(default=None, max_length=128)


class ChatTurnResponse(BaseModel):
    submission_id: str
    version: PositiveInt
    status: Literal["admitted", "queued", "failed"]
    turn_id: str | None = None
    queue_position: PositiveInt | None = None
    error: str | None = None


class PendingSubmissionItem(BaseModel):
    submission_id: str
    version: PositiveInt
    status: Literal["queued", "failed"] = "queued"
    queue_position: PositiveInt
    message: str
    mode: Literal["chat", "agent"]
    execution_mode: Literal["standard", "auto"] = "standard"
    question_indexes: list[PositiveInt] = Field(default_factory=list)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    object_references: list[ProductObjectReference] = Field(default_factory=list)
    source_client_id: str | None = None
    error: str | None = None


class PendingSubmissionUpdateRequest(BaseModel):
    expected_version: PositiveInt
    message: str = Field(min_length=1, max_length=100_000)
    attachments: list[AttachmentRef] = Field(default_factory=list, max_length=10)
    question_indexes: list[PositiveInt] = Field(default_factory=list)
    object_references: list[ProductObjectReference] = Field(
        default_factory=list,
        max_length=8,
    )
    mode: Literal["chat", "agent"]
    execution_mode: Literal["standard", "auto"] = "standard"


class PendingSubmissionCommandRequest(BaseModel):
    expected_version: PositiveInt


class AttachmentDraftCreateRequest(BaseModel):
    file_asset_id: str = Field(min_length=1, max_length=128)
    draft_id: str | None = Field(default=None, min_length=1, max_length=128)


class AttachmentDraftResponse(BaseModel):
    draft_id: str
    file_asset_id: str
    conversation_id: str
    filename: str
    status: Literal["processing", "ready", "failed", "removed"]
    error_message: str | None = None


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class SessionExecutionModeUpdateRequest(BaseModel):
    execution_mode: Literal["standard", "auto"]
    expected_version: int = Field(ge=0)


class SessionExecutionModeResponse(BaseModel):
    session_id: str
    execution_mode: Literal["standard", "auto"]
    version: int = Field(ge=0)


# ── Mock-interview DTOs ──────────────────────────────────────────────────
# The start endpoint owns creation of the
# interview_record + conversation + mock_interview_runtime; subsequent calls
# address the run by ``record_id``. No "Runtime Director" — the next
# interviewer line is generated from plan_json + current stage + message
# history. Mirrored 1:1 by the TS interfaces in frontend/src/types/api.ts.


class MockStartRequest(BaseModel):
    resume_id: str = Field(min_length=1)
    jd_text: str = Field(min_length=20, max_length=50_000)
    interviewer_style: Literal["friendly", "professional", "rigorous", "pressure"] = (
        "professional"
    )
    # Advisory whole-interview length. This activates a prompt reminder but
    # never caps a stage or forcibly ends the interview.
    target_question_count: Literal[15, 20, 30] = 20
    job_opportunity_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=35,
    )

    @field_validator("resume_id", "jd_text", mode="before")
    @classmethod
    def strip_required_context(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class MockLiveMessage(BaseModel):
    id: int
    speaker: Literal["interviewer", "candidate"]
    text: str


class MockStartResp(BaseModel):
    """``POST /mock-interviews/start`` — atomic create + opening line."""

    record_id: str
    message: MockLiveMessage


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

    message: MockLiveMessage
    # Advisory only; the candidate still decides when to finish.
    end_suggested: bool


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
    None. Sourced from the user's single live ``mock_interview_runtime`` row.
    """

    has_in_progress: bool
    record_id: str | None = None
    title: str | None = None
    last_activity_at: str | None = None


class MockLiveStateResp(BaseModel):
    messages: list[MockLiveMessage]


class MockParseJdResp(BaseModel):
    """``POST /mock-interviews/parse-jd``."""

    text: str
    filename: str | None = None
    chars: int


class MockAnswerAudioResp(BaseModel):
    """``POST /mock-interviews/{record_id}/answer-audio``."""

    text: str
    audio_file_asset_id: str


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


__all__ = [
    # Generic chat session DTOs
    "SessionCreateRequest",
    "SessionCreateResponse",
    "SessionListItem",
    "AttachmentRef",
    "ChatTurnRequest",
    "ChatTurnResponse",
    "PendingSubmissionItem",
    "PendingSubmissionUpdateRequest",
    "PendingSubmissionCommandRequest",
    "ProductObjectKind",
    "ProductObjectReference",
    "AttachmentDraftCreateRequest",
    "AttachmentDraftResponse",
    "SessionRenameRequest",
    "SessionExecutionModeUpdateRequest",
    "SessionExecutionModeResponse",
    # Mock-interview DTOs (mirrored 1:1 by frontend/src/types/api.ts)
    "MockStartRequest",
    "MockLiveMessage",
    "MockStartResp",
    "MockAnswerRequest",
    "MockAnswerResp",
    "MockFinishResp",
    "MockRetryReviewResp",
    "MockAbandonResp",
    "MockInProgressResp",
    "MockLiveStateResp",
    "MockParseJdResp",
    "MockAnswerAudioResp",
    "TTSRequest",
]
