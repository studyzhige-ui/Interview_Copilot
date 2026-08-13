"""Concrete Agent tools for the implemented career-product state.

The handlers are deliberately task-shaped rather than one CRUD tool per
domain object.  They call the same Application Services as the HTTP boundary,
and they only persist sources that can be checked against owned records.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.db.database import SessionLocal
from app.models.agent_execution import AgentToolCall
from app.models.artifact import Artifact
from app.models.chat import Conversation, ConversationMessage
from app.schemas.artifact import (
    ArtifactProvenanceInput,
    ArtifactVersionView,
    ArtifactWriteInput,
)
from app.schemas.job_opportunity import (
    JobOpportunityView,
    NextActionCreate,
    NextActionView,
    OpportunityCreate,
    OpportunityDirectionSelection,
    ProcessEventAppend,
    ProcessEventView,
)
from app.services import artifact_service
from app.services.career_process_service import (
    CareerObjectNotFoundError,
    CareerProcessError,
    append_confirmed_process_event,
    create_job_opportunity,
    create_next_action,
    list_job_opportunities,
    list_next_actions,
)
from app.services.career_profile_service import (
    CareerProfileNotFoundError,
    get_career_profile,
)


class CareerContextArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_archived_opportunities: bool = False
    action_statuses: list[Literal["suggested", "planned", "done", "closed"]] = Field(
        default_factory=lambda: ["suggested", "planned"], max_length=4
    )
    opportunity_limit: int = Field(default=50, ge=1, le=100)
    action_limit: int = Field(default=100, ge=1, le=200)


class TrackSearchJobArgs(BaseModel):
    """Admit one exact posting from an audited successful search_jobs call."""

    model_config = ConfigDict(extra="forbid")

    search_call_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=200)
    confirmation_message_id: int = Field(gt=0)
    occurred_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=200)
    directions: list[OpportunityDirectionSelection] = Field(
        default_factory=list,
        max_length=20,
    )


class DerivedNextActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2_000)
    time_kind: Literal["fixed", "deadline", "flexible"] = "flexible"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    due_at: datetime | None = None
    original_time_text: str | None = Field(default=None, max_length=300)
    source_timezone: str | None = Field(default=None, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=200)


class RecordCareerEventArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opportunity_id: str = Field(min_length=1, max_length=35)
    kind: Literal[
        "application_submitted",
        "application_acknowledged",
        "recruiter_contact",
        "assessment_invited",
        "assessment_completed",
        "hiring_step",
        "interview_scheduled",
        "interview_completed",
        "background_check_started",
        "offer_received",
        "rejected",
        "withdrawn",
        "posting_closed",
        "offer_declined",
        "offer_accepted",
    ]
    occurred_at: datetime
    confirmation_message_id: int = Field(gt=0)
    description: str = Field(min_length=1, max_length=10_000)
    step_summary: str | None = Field(default=None, max_length=300)
    idempotency_key: str = Field(min_length=1, max_length=300)
    next_action: DerivedNextActionInput | None = None

    @model_validator(mode="after")
    def validate_hiring_step(self) -> "RecordCareerEventArgs":
        if self.kind == "hiring_step" and not (self.step_summary or "").strip():
            raise ValueError("hiring_step requires step_summary")
        return self


class ReadArtifactsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str | None = Field(default=None, min_length=1, max_length=128)
    include_archived: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SaveArtifactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(min_length=1, max_length=128)
    artifact_kind: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=240)
    content_text: str = Field(min_length=1)
    content_format: str = Field(default="markdown", min_length=1, max_length=64)


_TASK_REFUSAL_MARKERS = (
    "不要",
    "别",
    "不需要",
    "无需",
    "不必",
    "暂不",
    "先不",
    "禁止",
    "不保存",
    "不跟踪",
    "不追踪",
    "不记录",
    "不更新",
    "不标记",
    "do not",
    "don't",
    "dont",
    "no need",
    "not now",
    "never",
    "without saving",
    "without tracking",
    "without recording",
)

_TASK_NON_COMMAND_MARKERS = (
    "如何",
    "怎么",
    "怎样",
    "教程",
    "是否应该",
    "要不要",
    "how to",
    "how do",
    "how can",
    "how about",
    "should i",
    "tell me how",
    "what if",
    "whether",
)

_TASK_REQUEST_MARKERS = (
    "请",
    "帮我",
    "麻烦",
    "给我",
    "我要",
    "我想",
    "需要你",
    "please",
    "for me",
    "can you",
    "could you",
    "would you",
    "i want you to",
    "help me",
    "go ahead and",
)


def _task_explicitly_authorizes(
    current_task: str,
    *,
    action_words: tuple[str, ...],
    target_words: tuple[str, ...],
) -> bool:
    """Narrow a redundant approval only for an explicit current action.

    This text predicate is deliberately conservative. It cannot establish
    ownership, source validity, object state, or legal transitions; the typed
    handler and its Application Service still enforce all of those. Any
    refusal wins, and ambiguous wording falls back to the exact-call ask path.
    """

    normalized = current_task.casefold()
    if any(marker in normalized for marker in _TASK_REFUSAL_MARKERS):
        return False
    if any(marker in normalized for marker in _TASK_NON_COMMAND_MARKERS):
        return False

    def contains(term: str) -> bool:
        if not term.isascii():
            return term in normalized
        # Do not let `record` match `recording` or `mark` match `markdown`.
        return (
            re.search(
                rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])",
                normalized,
            )
            is not None
        )

    matching_actions = [word for word in action_words if contains(word)]
    if not matching_actions or not any(contains(word) for word in target_words):
        return False
    normalized_without_leading_punctuation = normalized.lstrip(
        " \t\r\n，。！？,.!?:：;；"
    )
    return (
        any(marker in normalized for marker in _TASK_REQUEST_MARKERS)
        or normalized_without_leading_punctuation.startswith(("把", "将"))
        or any(
            normalized_without_leading_punctuation.startswith(word)
            for word in matching_actions
        )
    )


def _task_authorizes_track_search_job(
    _arguments: dict[str, Any],
    _ctx: AgentToolContext,
    current_task: str,
) -> bool:
    return _task_explicitly_authorizes(
        current_task,
        action_words=(
            "跟踪",
            "追踪",
            "保存",
            "加入",
            "纳入",
            "track",
            "save",
            "add",
        ),
        target_words=(
            "岗位",
            "职位",
            "工作机会",
            "job",
            "position",
            "opportunity",
            "posting",
        ),
    )


def _task_authorizes_record_career_event(
    _arguments: dict[str, Any],
    _ctx: AgentToolContext,
    current_task: str,
) -> bool:
    return _task_explicitly_authorizes(
        current_task,
        action_words=(
            "记录",
            "登记",
            "更新",
            "标记",
            "记下",
            "记一下",
            "记入",
            "record",
            "log",
            "update",
            "mark",
        ),
        target_words=(
            "状态",
            "进展",
            "事件",
            "流程",
            "面试",
            "投递",
            "申请",
            "测评",
            "背调",
            "offer",
            "拒绝",
            "淘汰",
            "录用",
            "入职",
            "status",
            "progress",
            "event",
            "interview",
            "application",
            "applied",
            "assessment",
            "background check",
            "rejected",
            "hiring",
        ),
    )


def _task_authorizes_save_artifact(
    _arguments: dict[str, Any],
    _ctx: AgentToolContext,
    current_task: str,
) -> bool:
    return _task_explicitly_authorizes(
        current_task,
        action_words=(
            "保存",
            "存档",
            "归档",
            "留存",
            "存下来",
            "收录",
            "save",
            "archive",
            "keep",
            "store",
        ),
        target_words=(
            "材料",
            "文档",
            "报告",
            "计划",
            "内容",
            "回答",
            "产物",
            "文件",
            "笔记",
            "草稿",
            "总结",
            "artifact",
            "document",
            "report",
            "plan",
            "content",
            "answer",
            "file",
            "note",
            "draft",
            "summary",
        ),
    )


def _scope(ctx: AgentToolContext) -> tuple[int, str | None]:
    if ctx.user_pk is None or ctx.user_pk <= 0:
        raise ValueError("career_tool_user_scope_unavailable")
    return ctx.user_pk, ctx.turn_id


def _owned_user_message(db, *, user_pk: int, message_id: int) -> ConversationMessage:
    row = (
        db.query(ConversationMessage)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .filter(
            ConversationMessage.id == message_id,
            ConversationMessage.role.ilike("user"),
            Conversation.user_id == user_pk,
        )
        .one_or_none()
    )
    if row is None:
        raise ValueError("confirmation_message_not_found_or_not_owned")
    return row


def _job_from_search_call(
    db,
    *,
    user_pk: int,
    session_id: str,
    search_call_id: str,
    job_id: str,
) -> tuple[AgentToolCall, dict[str, Any]]:
    call = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.call_id == search_call_id,
            AgentToolCall.user_id == user_pk,
            AgentToolCall.session_id == session_id,
            AgentToolCall.tool_name == "search_jobs",
            AgentToolCall.status == "completed",
        )
        .one_or_none()
    )
    if call is None or not isinstance(call.result_json, dict):
        raise ValueError("search_result_not_found_or_not_owned")
    if call.result_json.get("truncated"):
        raise ValueError("search_result_not_available_for_admission")
    candidates: list[Any]
    if isinstance(call.result_json.get("jobs"), list):
        candidates = call.result_json["jobs"]
    else:
        candidates = [call.result_json]
    job = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and str(item.get("job_id") or "") == job_id
        ),
        None,
    )
    if job is None:
        raise ValueError("job_not_present_in_search_result")
    return call, job


def _artifact_payload(db, *, user_pk: int, artifact, include_archived: bool) -> dict:
    version = artifact_service.get_current_artifact_version(
        db,
        user_pk=user_pk,
        artifact_id=artifact.id,
        include_archived=include_archived,
    )
    return {
        "id": artifact.id,
        "kind": artifact.kind,
        "archived_at": artifact.archived_at,
        "current_version": ArtifactVersionView.model_validate(version).model_dump(
            mode="json"
        ),
    }


def _known_error(exc: Exception) -> dict[str, Any] | None:
    if isinstance(
        exc,
        (
            CareerObjectNotFoundError,
            artifact_service.ArtifactNotFoundError,
            artifact_service.ArtifactOwnershipError,
            artifact_service.ArtifactSourceUnavailableError,
        ),
    ):
        return {"error": "not_found_or_not_owned"}
    if isinstance(exc, (CareerProcessError, artifact_service.ArtifactDomainError)):
        return {"error": "domain_command_rejected", "detail": str(exc)}
    if isinstance(exc, CareerProfileNotFoundError):
        return {"error": "career_profile_not_found"}
    return None


async def read_career_context(
    args: CareerContextArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk, _turn_id = _scope(ctx)

    def read() -> dict[str, Any]:
        db = SessionLocal()
        try:
            try:
                profile = get_career_profile(db, user_pk=user_pk).model_dump(
                    mode="json"
                )
            except CareerProfileNotFoundError:
                profile = None
            opportunities = list_job_opportunities(
                db,
                user_pk=user_pk,
                include_archived=args.include_archived_opportunities,
                limit=args.opportunity_limit,
            )
            actions = list_next_actions(
                db,
                user_pk=user_pk,
                statuses=set(args.action_statuses),
                limit=args.action_limit,
            )
            return {
                "career_profile": profile,
                "job_opportunities": [
                    JobOpportunityView.model_validate(row).model_dump(mode="json")
                    for row in opportunities
                ],
                "next_actions": [
                    NextActionView.model_validate(row).model_dump(mode="json")
                    for row in actions
                ],
            }
        finally:
            db.close()

    return await asyncio.to_thread(read)


async def track_search_job(
    args: TrackSearchJobArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk, _turn_id = _scope(ctx)

    def write() -> dict[str, Any]:
        db = SessionLocal()
        try:
            confirmation = _owned_user_message(
                db,
                user_pk=user_pk,
                message_id=args.confirmation_message_id,
            )
            call, job = _job_from_search_call(
                db,
                user_pk=user_pk,
                session_id=ctx.session_id,
                search_call_id=args.search_call_id,
                job_id=args.job_id,
            )
            provider = str(job.get("site") or job.get("source") or "lever")
            admission = create_job_opportunity(
                db,
                user_pk=user_pk,
                command=OpportunityCreate(
                    company_name=provider,
                    job_title=str(job.get("title") or "").strip(),
                    entry_reason="explicit_tracking",
                    occurred_at=args.occurred_at,
                    source_kind="tool_result",
                    source_identity=call.call_id,
                    source_version=str(call.id),
                    source_description=(
                        f"用户在消息 {confirmation.id} 中明确确认纳入；"
                        "岗位字段来自已完成的 search_jobs 结果。"
                    ),
                    location=str(job.get("location") or "").strip() or None,
                    team=str(job.get("team") or "").strip() or None,
                    source_url=(
                        str(job.get("hosted_url") or job.get("apply_url") or "").strip()
                        or None
                    ),
                    source_provider=provider,
                    external_job_id=args.job_id,
                    idempotency_key=args.idempotency_key,
                    directions=args.directions,
                ),
            )
            payload = JobOpportunityView.model_validate(
                admission.opportunity
            ).model_dump(mode="json")
            db.commit()
            return {"job_opportunity": payload, "created": admission.created}
        except Exception as exc:
            db.rollback()
            known = _known_error(exc)
            if known is not None:
                return known
            raise
        finally:
            db.close()

    return await asyncio.to_thread(write)


async def record_career_event(
    args: RecordCareerEventArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk, _turn_id = _scope(ctx)

    def write() -> dict[str, Any]:
        db = SessionLocal()
        try:
            confirmation = _owned_user_message(
                db,
                user_pk=user_pk,
                message_id=args.confirmation_message_id,
            )
            event = append_confirmed_process_event(
                db,
                user_pk=user_pk,
                opportunity_id=args.opportunity_id,
                command=ProcessEventAppend(
                    kind=args.kind,
                    occurred_at=args.occurred_at,
                    source_kind="user_assertion",
                    source_identity=f"conversation_message:{confirmation.id}",
                    description=args.description,
                    step_summary=args.step_summary,
                    idempotency_key=args.idempotency_key,
                ),
            )
            action = None
            if args.next_action is not None:
                action_input = args.next_action
                action = create_next_action(
                    db,
                    user_pk=user_pk,
                    command=NextActionCreate(
                        content=action_input.content,
                        status="suggested",
                        time_kind=action_input.time_kind,
                        starts_at=action_input.starts_at,
                        ends_at=action_input.ends_at,
                        due_at=action_input.due_at,
                        original_time_text=action_input.original_time_text,
                        source_timezone=action_input.source_timezone,
                        source_kind="process_event",
                        source_identity=event.id,
                        job_opportunity_id=args.opportunity_id,
                        idempotency_key=action_input.idempotency_key,
                    ),
                )
            event_payload = ProcessEventView.model_validate(event).model_dump(
                mode="json"
            )
            action_payload = (
                NextActionView.model_validate(action).model_dump(mode="json")
                if action is not None
                else None
            )
            db.commit()
            return {"process_event": event_payload, "next_action": action_payload}
        except Exception as exc:
            db.rollback()
            known = _known_error(exc)
            if known is not None:
                return known
            raise
        finally:
            db.close()

    return await asyncio.to_thread(write)


async def read_artifacts(
    args: ReadArtifactsArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk, _turn_id = _scope(ctx)

    def read() -> dict[str, Any]:
        db = SessionLocal()
        try:
            if args.artifact_id:
                version = artifact_service.get_current_artifact_version(
                    db,
                    user_pk=user_pk,
                    artifact_id=args.artifact_id,
                    include_archived=args.include_archived,
                )
                owned = (
                    db.query(Artifact)
                    .filter(
                        Artifact.id == args.artifact_id, Artifact.user_id == user_pk
                    )
                    .one()
                )
                return {
                    "artifacts": [
                        {
                            "id": owned.id,
                            "kind": owned.kind,
                            "archived_at": owned.archived_at,
                            "current_version": ArtifactVersionView.model_validate(
                                version
                            ).model_dump(mode="json"),
                        }
                    ]
                }
            rows = artifact_service.list_artifacts(
                db,
                user_pk=user_pk,
                include_archived=args.include_archived,
                limit=args.limit,
                offset=args.offset,
            )
            return {
                "artifacts": [
                    {
                        "id": artifact.id,
                        "kind": artifact.kind,
                        "archived_at": artifact.archived_at,
                        "current_version": ArtifactVersionView.model_validate(
                            version
                        ).model_dump(mode="json"),
                    }
                    for artifact, version in rows
                ]
            }
        except Exception as exc:
            known = _known_error(exc)
            if known is not None:
                return known
            raise
        finally:
            db.close()

    return await asyncio.to_thread(read)


async def save_artifact(
    args: SaveArtifactArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk, turn_id = _scope(ctx)
    if not turn_id:
        raise ValueError("artifact_source_turn_unavailable")

    def write() -> dict[str, Any]:
        db = SessionLocal()
        try:
            artifact = artifact_service.save_artifact_explicitly(
                db,
                user_pk=user_pk,
                operation_key=args.operation_key,
                artifact_kind=args.artifact_kind,
                version=ArtifactWriteInput(
                    title=args.title,
                    content_text=args.content_text,
                    content_format=args.content_format,
                    provenance=ArtifactProvenanceInput(source_turn_id=turn_id),
                ),
            )
            payload = _artifact_payload(
                db,
                user_pk=user_pk,
                artifact=artifact,
                include_archived=False,
            )
            db.commit()
            return {"artifact": payload}
        except Exception as exc:
            db.rollback()
            known = _known_error(exc)
            if known is not None:
                return known
            raise
        finally:
            db.close()

    return await asyncio.to_thread(write)


registry.register(
    ToolDefinition(
        name="read_career_context",
        description=(
            "Read the user's confirmed CareerProfile and directions together with "
            "their tracked job opportunities and durable NextActions."
        ),
        args_model=CareerContextArgs,
        handler=read_career_context,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        emoji="🧭",
    )
)

registry.register(
    ToolDefinition(
        name="track_search_job",
        description=(
            "After explicit user confirmation, admit one exact posting from a "
            "completed owned search_jobs call into JobOpportunity tracking."
        ),
        args_model=TrackSearchJobArgs,
        handler=track_search_job,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_track_search_job,
        concurrency_safe=False,
        emoji="📌",
        prompt=(
            "Never copy model-written job fields into this tool. Pass the call id "
            "of a real completed search_jobs result, its exact job_id, and the "
            "owned user message that confirms tracking."
        ),
    )
)

registry.register(
    ToolDefinition(
        name="record_career_event",
        description=(
            "Record one user-confirmed hiring-process fact and optionally derive "
            "one suggested NextAction from that new ProcessEvent atomically."
        ),
        args_model=RecordCareerEventArgs,
        handler=record_career_event,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_record_career_event,
        concurrency_safe=False,
        emoji="🗂️",
    )
)

registry.register(
    ToolDefinition(
        name="read_artifacts",
        description="Read the user's explicitly saved Artifact assets and current versions.",
        args_model=ReadArtifactsArgs,
        handler=read_artifacts,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        emoji="📄",
    )
)

registry.register(
    ToolDefinition(
        name="save_artifact",
        description=(
            "Explicitly save substantial current-Turn content as a durable Artifact; "
            "ordinary assistant answers are not saved automatically."
        ),
        args_model=SaveArtifactArgs,
        handler=save_artifact,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_save_artifact,
        concurrency_safe=False,
        emoji="💾",
    )
)


__all__ = [
    "read_artifacts",
    "read_career_context",
    "record_career_event",
    "save_artifact",
    "track_search_job",
]
