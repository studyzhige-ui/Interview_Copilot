"""Pydantic schemas for chat / mock-interview HTTP endpoints."""

from pydantic import BaseModel


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


class MockStartRequest(BaseModel):
    session_id: str
    resume_upload_id: str | None = None
    jd_upload_id: str | None = None


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
