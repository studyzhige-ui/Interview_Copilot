"""One explicit WebRTC handshake and bounded, generation-fenced control DTO."""

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MediaOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_session_id: UUID
    sdp: str = Field(min_length=1, max_length=65536)
    type: Literal["offer"] = "offer"


class MediaAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str
    client_session_id: str
    sdp: str
    type: Literal["answer"] = "answer"


class MediaControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connection_id: str = Field(min_length=36, max_length=36)
    action: Literal[
        "ping", "interrupt", "finish", "commit", "discard", "ack", "play_question"
    ]
    request_id: str | None = Field(None, min_length=36, max_length=36)
    playback_id: str | None = Field(None, min_length=36, max_length=36)
    samples: int | None = Field(None, ge=0, le=24_000 * 600)

    @model_validator(mode="after")
    def fields_match_action(self):
        if (self.action == "commit") != (self.request_id is not None):
            raise ValueError("commit_requires_exact_request_id")
        if (self.action == "ack") != (
            self.playback_id is not None and self.samples is not None
        ):
            raise ValueError("ack_requires_playback_and_samples")
        if self.action != "ack" and (
            self.playback_id is not None or self.samples is not None
        ):
            raise ValueError("unexpected_ack_fields")
        return self


class MediaPlaybackReport(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    playback_id: str
    message_id: int
    generated_samples: int = Field(ge=0)
    delivered_samples: int = Field(ge=0)
    client_reported_samples: int = Field(ge=0)
    sample_rate: int = Field(gt=0)
    status: Literal["completed", "interrupted", "failed"]
