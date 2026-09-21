"""Versioned signalling/control contract; provisional text is never an answer."""

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class MediaOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_session_id: UUID
    sdp: str = Field(min_length=1, max_length=65536)
    type: Literal["offer"] = "offer"
    auto_submit: bool = False


class MediaAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    generation: int
    sdp: str
    type: Literal["answer"] = "answer"
    protocol: Literal["interview-media-v1"] = "interview-media-v1"


class MediaCommand(BaseModel):
    """Each action has an exact field set, checked before application dispatch."""

    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal[
        "sync",
        "finish_utterance",
        "discard",
        "commit",
        "interrupt",
        "speak",
        "playback",
    ]
    draft_id: str | None = Field(default=None, max_length=36)
    request_id: str | None = Field(default=None, max_length=36)
    audio_id: str | None = Field(default=None, max_length=36)
    played_samples: int | None = Field(default=None, ge=0, le=1440000)
    complete: bool | None = None

    @field_validator("draft_id", "request_id", "audio_id")
    @classmethod
    def validate_id(cls, value):
        return str(UUID(value)) if value is not None else None

    def checked(self):
        required = {
            "commit": {"type", "draft_id", "request_id"},
            "playback": {"type", "audio_id", "played_samples", "complete"},
        }.get(self.type, {"type"})
        if self.model_fields_set != required or any(
            getattr(self, name) is None for name in required
        ):
            raise ValueError("invalid_media_command_fields")
        return self


class MediaGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    generation: int = Field(ge=1)


class MediaEvent(BaseModel):
    """Server events validated before serializing onto the encrypted channel."""

    model_config = ConfigDict(extra="forbid", strict=True)
    v: Literal[1] = 1
    generation: int = Field(ge=1)
    seq: int = Field(ge=1)
    type: Literal[
        "state",
        "speech_start",
        "partial",
        "final",
        "cleared",
        "submitting",
        "answer",
        "interrupt",
        "audio_start",
        "audio",
        "audio_end",
        "speech_done",
        "notice",
        "error",
    ]
    question: dict | None = None
    answer_pending: bool | None = None
    request_id: str | None = None
    request_status: Literal["in_progress", "completed", "unknown"] | None = None
    code: str | None = Field(default=None, max_length=80)
    text: str | None = Field(default=None, max_length=16000)
    draft_id: str | None = None
    message: dict | None = None
    end_suggested: bool | None = None
    audio_id: str | None = None
    rate: Literal[24000] | None = None
    samples: int | None = Field(default=None, ge=1, le=1440000)
    offset: int | None = Field(default=None, ge=0, le=1440000)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    pcm: str | None = Field(default=None, max_length=16384)
