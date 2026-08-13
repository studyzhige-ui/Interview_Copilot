"""Task-shaped resume-to-profile candidate commands for the shared Agent."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.db.database import SessionLocal
from app.models.chat import Conversation, ConversationMessage
from app.schemas.career_profile import (
    CareerProfileCandidateBatchResolutionInput,
    CareerProfileCandidateDecisionInput,
)
from app.services import career_profile_service
from app.services.resume import resume_artifact_service


class PrepareResumeProfileCandidatesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_artifact_id: str = Field(min_length=1, max_length=128)


class CandidateDecisionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=37)
    expected_version: int = Field(ge=1)
    decision: Literal["accept", "reject"]
    note: str | None = Field(default=None, max_length=2_000)


class ResolveResumeProfileCandidatesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=37)
    expected_draft_version: int = Field(ge=1)
    expected_profile_version: int = Field(ge=1)
    confirmation_message_id: int = Field(gt=0)
    decisions: list[CandidateDecisionArgs] = Field(min_length=1, max_length=250)


def _user_pk(ctx: AgentToolContext) -> int:
    if ctx.user_pk is None or ctx.user_pk <= 0:
        raise ValueError("resume_profile_user_scope_unavailable")
    return ctx.user_pk


async def prepare_resume_profile_candidates(
    args: PrepareResumeProfileCandidatesArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _user_pk(ctx)

    def read() -> tuple[str, str, str | None]:
        with SessionLocal() as db:
            record = resume_artifact_service.resolve_owned_resume(
                db, user_pk=user_pk, resume_id=args.resume_artifact_id
            )
            text = resume_artifact_service.read_resume_text(record)
            return text, record.current_version.id, record.artifact.id

    text, source_version_id, artifact_id = await asyncio.to_thread(read)
    candidates = await resume_artifact_service.extract_profile_candidates(
        text, user_id=ctx.user_id
    )

    def persist() -> dict[str, Any]:
        with SessionLocal() as db:
            try:
                record = resume_artifact_service.persist_extracted_resume(
                    db,
                    user_pk=user_pk,
                    resume_id=artifact_id,
                    source_version_id=source_version_id,
                    text=text,
                    candidates=candidates,
                )
                db.commit()
                return {
                    "resume_artifact_id": record.artifact.id,
                    "source_artifact_version_id": record.current_version.id,
                    "profile_draft_id": record.pending_draft_id,
                    "candidate_fact_count": len(candidates.facts),
                    "candidate_direction_count": len(candidates.directions),
                    "requires_user_confirmation": bool(
                        candidates.facts or candidates.directions
                    ),
                }
            except Exception:
                db.rollback()
                raise

    return await asyncio.to_thread(persist)


async def resolve_resume_profile_candidates(
    args: ResolveResumeProfileCandidatesArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _user_pk(ctx)

    def write() -> dict[str, Any]:
        with SessionLocal() as db:
            confirmation = (
                db.query(ConversationMessage.id)
                .join(
                    Conversation,
                    Conversation.id == ConversationMessage.conversation_id,
                )
                .filter(
                    ConversationMessage.id == args.confirmation_message_id,
                    ConversationMessage.role.ilike("user"),
                    Conversation.user_id == user_pk,
                )
                .scalar()
            )
            if confirmation is None:
                raise ValueError("profile_candidate_confirmation_message_not_owned")
            result = career_profile_service.resolve_profile_candidate_items(
                db,
                user_pk=user_pk,
                draft_id=args.draft_id,
                resolution=CareerProfileCandidateBatchResolutionInput(
                    expected_draft_version=args.expected_draft_version,
                    expected_profile_version=args.expected_profile_version,
                    decisions=[
                        CareerProfileCandidateDecisionInput(
                            item_id=decision.item_id,
                            expected_version=decision.expected_version,
                            decision=decision.decision,
                            note=(
                                decision.note
                                or f"Confirmed in user message {args.confirmation_message_id}"
                            ),
                        )
                        for decision in args.decisions
                    ],
                ),
            )
            db.commit()
            return result.model_dump(mode="json")

    return await asyncio.to_thread(write)


registry.register(
    ToolDefinition(
        name="prepare_resume_profile_candidates",
        description=(
            "Extract reviewable CareerProfile candidates from one already-saved "
            "resume Artifact. It never confirms or overwrites profile facts."
        ),
        args_model=PrepareResumeProfileCandidatesArgs,
        handler=prepare_resume_profile_candidates,
        effect=ToolEffect.INTERNAL_WRITE,
        concurrency_safe=False,
        emoji="🧾",
    )
)

registry.register(
    ToolDefinition(
        name="resolve_resume_profile_candidates",
        description=(
            "Accept or reject existing resume-derived candidate item identities "
            "after an owned user message explicitly confirms those decisions."
        ),
        args_model=ResolveResumeProfileCandidatesArgs,
        handler=resolve_resume_profile_candidates,
        effect=ToolEffect.INTERNAL_WRITE,
        concurrency_safe=False,
        emoji="✅",
        prompt=(
            "Do not provide replacement facts in this call. Use only candidate "
            "ids/version tokens returned by the profile read and cite the exact "
            "user message that accepted or rejected them."
        ),
    )
)


__all__ = [
    "prepare_resume_profile_candidates",
    "resolve_resume_profile_candidates",
]
