"""Product runtime profiles layered on top of the shared conversation kernel.

The kernel owns transport, context budgeting, persistence, and strategy
execution. A runtime profile owns product-specific context and mode policy.
This keeps the career control plane independent from debrief-only record data
without duplicating the reliable low-level conversation machinery.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.chat.interview_reference import (
    InterviewReference,
    load_interview_reference,
    render_interview_reference,
)

ConversationMode = str


@dataclass(frozen=True)
class RuntimeTurnContext:
    """Product-specific material prepared once for a conversation turn."""

    profile: str
    interview_reference: InterviewReference | None = None

    @property
    def planner_question_catalog(self) -> list[tuple[int, str]] | None:
        reference = self.interview_reference
        return reference.question_catalog if reference is not None else None

    def render_record_context(
        self,
        explicit_question_indexes: tuple[int, ...],
        planned_question_indexes: tuple[int, ...],
    ) -> str:
        reference = self.interview_reference
        if reference is None:
            return ""
        valid_indexes = {index for index, _ in reference.question_catalog}
        focused_indexes = tuple(
            dict.fromkeys(
                index
                for index in (
                    *explicit_question_indexes,
                    *planned_question_indexes,
                )
                if index in valid_indexes
            )
        )
        return render_interview_reference(reference, focused_indexes)


@dataclass(frozen=True)
class ConversationRuntimeProfile:
    """Mode policy and domain-context loader for one product runtime."""

    name: str
    default_mode: ConversationMode
    allowed_modes: frozenset[ConversationMode]

    async def prepare_turn(
        self,
        session_meta: Mapping[str, Any] | None,
    ) -> RuntimeTurnContext:
        return RuntimeTurnContext(profile=self.name)

    def resolve_mode(
        self,
        persisted: ConversationMode | None,
        requested: ConversationMode | None,
    ) -> ConversationMode:
        candidate = requested or persisted or self.default_mode
        return candidate if candidate in self.allowed_modes else self.default_mode


class DebriefRuntimeProfile(ConversationRuntimeProfile):
    async def prepare_turn(
        self,
        session_meta: Mapping[str, Any] | None,
    ) -> RuntimeTurnContext:
        if (
            session_meta is None
            or session_meta.get("subject_type") != "interview_record"
            or not session_meta.get("subject_id")
        ):
            return RuntimeTurnContext(profile=self.name)

        reference = await asyncio.to_thread(
            load_interview_reference,
            str(session_meta["subject_id"]),
            int(session_meta["user_id"]),
        )
        return RuntimeTurnContext(
            profile=self.name,
            interview_reference=reference,
        )


CAREER_RUNTIME = ConversationRuntimeProfile(
    name="career",
    default_mode="agent",
    allowed_modes=frozenset({"agent"}),
)
DEBRIEF_RUNTIME = DebriefRuntimeProfile(
    name="debrief",
    default_mode="chat",
    allowed_modes=frozenset({"chat", "agent"}),
)
MOCK_INTERVIEW_RUNTIME = ConversationRuntimeProfile(
    name="mock_interview",
    default_mode="chat",
    allowed_modes=frozenset({"chat"}),
)


def runtime_profile_for_type(
    conversation_type: str | None,
) -> ConversationRuntimeProfile:
    if conversation_type == "debrief":
        return DEBRIEF_RUNTIME
    if conversation_type == "mock_interview":
        return MOCK_INTERVIEW_RUNTIME
    return CAREER_RUNTIME


def runtime_profile_for_session(
    session_meta: Mapping[str, Any] | None,
) -> ConversationRuntimeProfile:
    return runtime_profile_for_type(
        str(session_meta.get("type")) if session_meta is not None else None
    )


__all__ = [
    "CAREER_RUNTIME",
    "DEBRIEF_RUNTIME",
    "MOCK_INTERVIEW_RUNTIME",
    "ConversationRuntimeProfile",
    "RuntimeTurnContext",
    "runtime_profile_for_session",
    "runtime_profile_for_type",
]
