"""Strict inputs and judge outputs for mock evaluation, not production scoring."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Stage = Literal[
    "self_intro",
    "resume_project_deep_dive",
    "role_technical_assessment",
    "candidate_questions",
]
Text = Annotated[str, Field(max_length=100_000)]
Score = Annotated[int, Field(strict=True, ge=1, le=5)]
JUDGE_DIMENSIONS = (
    "relevance",
    "follow_up",
    "naturalness",
    "grounding",
    "safety",
    "language_fit",
)


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class JudgeResult(StrictContract):
    relevance: Score
    follow_up: Score
    naturalness: Score
    grounding: Score
    safety: Score
    language_fit: Score
    reason: Annotated[str, Field(min_length=1, max_length=4000)]

    @model_validator(mode="after")
    def meaningful_reason(self):
        if not self.reason.strip():
            raise ValueError("judge reason must not be whitespace")
        return self


class Message(StrictContract):
    role: Literal["user", "assistant", "agent"]
    content: Text


class Question(StrictContract):
    text: Text
    stage_key: Stage


class Step(StrictContract):
    answer: Text
    expect_finish: bool | None = None
    forbidden: list[str] = Field(default_factory=list, max_length=100)
    expected_language: Literal["zh", "en", "mixed", "any"] | None = None


class CommonCase(StrictContract):
    id: Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[\w.-]+$")]
    style: Literal["professional", "friendly", "rigorous", "pressure"]
    resume: Text
    jd: Text
    recent_messages: list[Message] = Field(default_factory=list, max_length=200)
    forbidden: list[str] = Field(default_factory=list, max_length=100)
    length_warning_active: bool = False
    expected_language: Literal["zh", "en", "mixed", "any"] | None = None


class TurnCase(CommonCase):
    current_stage: Stage
    user_answer: Text
    asked_questions: list[str] = Field(default_factory=list, max_length=200)
    allowed_stages: list[Stage] = Field(min_length=1, max_length=4)
    expect_finish: bool | None = None


class TrajectoryCase(CommonCase):
    current_stage: Stage = "self_intro"
    initial_questions: list[Question] = Field(default_factory=list, max_length=200)
    steps: list[Step] = Field(default_factory=list, max_length=64)
    answers_by_stage: dict[Stage, list[Text]] = Field(default_factory=dict)
    max_turns: Annotated[int, Field(ge=1, le=64)]
    warning_turns: Annotated[int, Field(ge=1, le=64)] = 20
    required_stages: list[Stage] = Field(default_factory=list, max_length=4)
    expect_complete: bool = False
    disconnect_after_turns: list[Annotated[int, Field(ge=1, le=64)]] = Field(
        default_factory=list, max_length=64
    )

    @model_validator(mode="after")
    def one_answer_source(self):
        if bool(self.steps) == bool(self.answers_by_stage):
            raise ValueError("trajectory requires exactly one nonempty answer source")
        if self.steps and len(self.steps) < self.max_turns:
            raise ValueError("steps must cover max_turns")
        if self.answers_by_stage and any(not v for v in self.answers_by_stage.values()):
            raise ValueError("stage answers must not be empty")
        if any(t > self.max_turns for t in self.disconnect_after_turns):
            raise ValueError("disconnect marker exceeds max_turns")
        return self


def strict_json(text: str, *, max_bytes: int = 1_000_000):
    """No duplicate keys, NaN, coercion, or unbounded model response parsing."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > max_bytes:
        raise ValueError("JSON input exceeds capacity")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_value):
        raise ValueError("nonfinite JSON number")

    try:
        return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    except RecursionError:
        raise ValueError("JSON input nesting exceeds parser capacity") from None
