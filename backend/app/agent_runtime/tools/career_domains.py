"""Task-shaped Agent adapters for canonical career product domains.

The module deliberately does not introduce a generic domain registry or a
model-owned patch language.  Every write delegates to the same typed
Application Service used by the product API, carries the authoritative user
and source identities, and revalidates the current Turn's exact user message
before changing state.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    model_validator,
)

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.db.database import SessionLocal
from app.models.artifact import ArtifactSubmissionSnapshot
from app.models.chat import ConversationMessage
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity, NextAction
from app.models.offer import Offer
from app.schemas.ability_signal import AbilitySignalView
from app.schemas.artifact import ArtifactSubmissionView
from app.schemas.career_insights import (
    AnnualBonusAssumption,
    EquityValuationAssumption,
    ExchangeRateAssumption,
    OfferAnalysisRequest,
    TaxAssumption,
)
from app.schemas.career_profile import (
    CareerProfileCandidateBatchResolutionInput,
    CareerProfileCandidateDecisionInput,
    ConfirmationInput,
    DirectionInput,
    PersonalFactInput,
)
from app.schemas.job_opportunity import (
    NextActionClose,
    NextActionCreate,
    NextActionEdit,
    NextActionTransition,
    NextActionView,
)
from app.schemas.offer import OfferView
from app.schemas.persistent_task import (
    PersistentTaskCreate,
    PersistentTaskStateChange,
    PersistentTaskTriggerInput,
    PersistentTaskTriggerSpec,
    PersistentTaskTriggerView,
    PersistentTaskUpdate,
    PersistentTaskView,
)
from app.services import (
    ability_signal_service,
    artifact_service,
    career_profile_service,
    offer_analysis_service,
    offer_service,
)
from app.services.career_process_service import (
    CareerObjectNotFoundError,
    CareerProcessError,
    close_next_action,
    complete_next_action,
    create_next_action,
    edit_next_action,
    plan_next_action,
)
from app.services.chat.current_turn_source import (
    CurrentTurnSourceError as CurrentTurnProofError,
    require_current_turn_user_message,
)

from .career import _task_explicitly_authorizes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared current-Turn proof
# ---------------------------------------------------------------------------


def _scope(ctx: AgentToolContext) -> int:
    if ctx.user_pk is None or ctx.user_pk <= 0:
        raise ValueError("career_domain_user_scope_unavailable")
    return ctx.user_pk


def _current_user_message(
    db,
    *,
    ctx: AgentToolContext,
    message_id: int,
) -> ConversationMessage:
    """Resolve the exact user message that admitted this Tool's current Turn."""

    return require_current_turn_user_message(
        db,
        user_pk=_scope(ctx),
        turn_id=ctx.turn_id,
        conversation_id=ctx.session_id,
        message_id=message_id,
    )


def _message_identity(message: ConversationMessage) -> str:
    return f"conversation_message:{message.id}"


def _resource(*values: str | None) -> tuple[str, ...]:
    return tuple(value for value in values if value)


def _command_operation(arguments: dict[str, Any]) -> str:
    command = arguments.get("command")
    return str(command.get("operation") or "") if isinstance(command, dict) else ""


def _persistent_tasks():
    """Import lazily to avoid Turn executor -> tools -> automation recursion."""

    from app.services import persistent_task_service

    return persistent_task_service


def _domain_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, CurrentTurnProofError):
        return {
            "error": "current_task_confirmation_required",
            "detail": str(exc),
        }
    if isinstance(
        exc,
        (
            CareerObjectNotFoundError,
            career_profile_service.CareerProfileNotFoundError,
            ability_signal_service.AbilitySignalNotFoundError,
            artifact_service.ArtifactNotFoundError,
            artifact_service.ArtifactOwnershipError,
            offer_analysis_service.OfferAnalysisNotFoundError,
        ),
    ):
        return {"error": "not_found_or_not_owned"}
    persistent_tasks = _persistent_tasks()
    if isinstance(exc, persistent_tasks.PersistentTaskNotFoundError):
        return {"error": "not_found_or_not_owned"}
    if isinstance(
        exc,
        (
            career_profile_service.CareerProfileError,
            ability_signal_service.AbilitySignalError,
            CareerProcessError,
            artifact_service.ArtifactDomainError,
            offer_analysis_service.OfferAnalysisError,
        ),
    ):
        return {"error": "domain_command_rejected", "detail": str(exc)}
    if isinstance(exc, persistent_tasks.PersistentTaskError):
        return {"error": "domain_command_rejected", "detail": str(exc)}
    raise exc


# ---------------------------------------------------------------------------
# Bounded cross-domain read
# ---------------------------------------------------------------------------


CareerReadSection = Literal[
    "profile_candidates",
    "ability_signals",
    "interviews",
    "offers",
    "persistent_tasks",
]


class ReadCareerDomainStateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[CareerReadSection] = Field(
        default_factory=lambda: [
            "profile_candidates",
            "ability_signals",
            "interviews",
            "offers",
            "persistent_tasks",
        ],
        min_length=1,
        max_length=5,
    )
    interview_record_id: str | None = Field(default=None, min_length=1, max_length=128)
    offer_id: str | None = Field(default=None, min_length=1, max_length=35)
    persistent_task_id: str | None = Field(default=None, min_length=1, max_length=128)
    include_inactive: bool = False
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def selectors_require_sections(self) -> "ReadCareerDomainStateArgs":
        required = {
            "interview_record_id": "interviews",
            "offer_id": "offers",
            "persistent_task_id": "persistent_tasks",
        }
        for field_name, section in required.items():
            if getattr(self, field_name) is not None and section not in self.sections:
                raise ValueError(f"{field_name} requires the {section} section")
        if len(self.sections) != len(set(self.sections)):
            raise ValueError("sections must be unique")
        return self


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _interview_view(row: InterviewRecord) -> dict[str, Any]:
    overall = _json_object(row.analysis_json).get("overall")
    return {
        "id": row.id,
        "source": row.source,
        "title": row.title,
        "status": row.status,
        "job_opportunity_id": row.job_opportunity_id,
        "debrief_guidance": row.debrief_guidance_text,
        "debrief_guidance_version": row.debrief_guidance_version,
        "ability_signal_generation": row.ability_signal_generation,
        "analysis_overall": overall if isinstance(overall, dict) else None,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "completed_at": row.completed_at,
        "detail_tool": {
            "name": "read_interview_history",
            "record_id": row.id,
        },
    }


async def read_career_domain_state(
    args: ReadCareerDomainStateArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _scope(ctx)

    def read() -> dict[str, Any]:
        db = SessionLocal()
        try:
            payload: dict[str, Any] = {}
            sections = set(args.sections)
            if "profile_candidates" in sections:
                try:
                    drafts = career_profile_service.list_profile_draft_views(
                        db,
                        user_pk=user_pk,
                        include_resolved=args.include_inactive,
                    )
                except career_profile_service.CareerProfileNotFoundError:
                    drafts = []
                payload["profile_candidates"] = [
                    item.model_dump(mode="json") for item in drafts[: args.limit]
                ]
            if "ability_signals" in sections:
                payload["ability_signals"] = [
                    item.model_dump(mode="json")
                    for item in ability_signal_service.list_ability_signals(
                        db,
                        user_pk=user_pk,
                        include_inactive=args.include_inactive,
                    )[: args.limit]
                ]
            if "interviews" in sections:
                query = db.query(InterviewRecord).filter(
                    InterviewRecord.user_id == user_pk
                )
                if args.interview_record_id:
                    query = query.filter(InterviewRecord.id == args.interview_record_id)
                rows = (
                    query.order_by(InterviewRecord.created_at.desc())
                    .limit(args.limit)
                    .all()
                )
                payload["interviews"] = [_interview_view(row) for row in rows]
            if "offers" in sections:
                query = (
                    db.query(Offer, JobOpportunity)
                    .join(JobOpportunity, JobOpportunity.id == Offer.job_opportunity_id)
                    .filter(
                        Offer.user_id == user_pk,
                        JobOpportunity.user_id == user_pk,
                    )
                )
                if args.offer_id:
                    query = query.filter(Offer.id == args.offer_id)
                rows = query.order_by(Offer.updated_at.desc()).limit(args.limit).all()
                payload["offers"] = [
                    {
                        "offer": OfferView.model_validate(offer).model_dump(
                            mode="json"
                        ),
                        "current_token": offer_service.current_offer_token(offer),
                        "company_name": opportunity.company_name,
                        "job_title": opportunity.job_title,
                    }
                    for offer, opportunity in rows
                ]
            if "persistent_tasks" in sections:
                persistent_tasks = _persistent_tasks()
                if args.persistent_task_id:
                    tasks = [
                        persistent_tasks.get_persistent_task(
                            db,
                            user_pk=user_pk,
                            task_id=args.persistent_task_id,
                        )
                    ]
                else:
                    tasks = persistent_tasks.list_persistent_tasks(db, user_pk=user_pk)[
                        : args.limit
                    ]
                payload["persistent_tasks"] = [
                    PersistentTaskView.model_validate(task).model_dump(mode="json")
                    for task in tasks
                ]
                if args.persistent_task_id:
                    payload["persistent_task_triggers"] = [
                        PersistentTaskTriggerView.model_validate(row).model_dump(
                            mode="json"
                        )
                        for row in persistent_tasks.list_persistent_task_triggers(
                            db,
                            user_pk=user_pk,
                            task_id=args.persistent_task_id,
                        )[: args.limit]
                    ]
            return payload
        except Exception as exc:
            return _domain_error(exc)
        finally:
            db.close()

    return await asyncio.to_thread(read)


# ---------------------------------------------------------------------------
# CareerProfile confirmed edits and candidate decisions
# ---------------------------------------------------------------------------


class ProfileFactUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["upsert_fact"]
    expected_profile_version: PositiveInt
    fact: PersonalFactInput
    fact_id: str | None = Field(default=None, min_length=1, max_length=128)


class ProfileFactRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["remove_fact"]
    expected_profile_version: PositiveInt
    fact_id: str = Field(min_length=1, max_length=128)


class ProfileDirectionUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["upsert_direction"]
    expected_profile_version: PositiveInt
    direction: DirectionInput
    direction_id: str | None = Field(default=None, min_length=1, max_length=128)


class ProfileDirectionLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["set_direction_lifecycle"]
    expected_profile_version: PositiveInt
    direction_id: str = Field(min_length=1, max_length=128)
    lifecycle: Literal["exploring", "active", "paused", "archived"]


class ProfileCandidateResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["resolve_candidates"]
    draft_id: str = Field(min_length=1, max_length=128)
    expected_draft_version: PositiveInt
    expected_profile_version: PositiveInt
    decisions: list[CareerProfileCandidateDecisionInput] = Field(
        min_length=1, max_length=250
    )


ProfileCommand = Annotated[
    ProfileFactUpsert
    | ProfileFactRemove
    | ProfileDirectionUpsert
    | ProfileDirectionLifecycle
    | ProfileCandidateResolution,
    Field(discriminator="operation"),
]


class ConfirmCareerProfileChangeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_message_id: PositiveInt
    command: ProfileCommand


def _task_authorizes_profile(
    arguments: dict[str, Any],
    ctx: AgentToolContext,
    current_task: str,
) -> bool:
    del ctx
    operation = _command_operation(arguments)
    action_words = {
        "upsert_fact": (
            "确认",
            "添加",
            "更新",
            "修改",
            "confirm",
            "add",
            "update",
            "change",
        ),
        "remove_fact": ("删除", "移除", "remove", "delete"),
        "upsert_direction": (
            "确认",
            "添加",
            "更新",
            "修改",
            "confirm",
            "add",
            "update",
            "change",
        ),
        "set_direction_lifecycle": (
            "探索",
            "启用",
            "激活",
            "暂停",
            "归档",
            "explore",
            "activate",
            "pause",
            "archive",
        ),
        "resolve_candidates": (
            "确认",
            "接受",
            "拒绝",
            "处理",
            "confirm",
            "accept",
            "reject",
            "resolve",
        ),
    }.get(operation)
    if action_words is None:
        return False
    return _task_explicitly_authorizes(
        current_task,
        action_words=action_words,
        target_words=(
            "求职档案",
            "个人详情",
            "个人事实",
            "目标方向",
            "候选项",
            "profile",
            "fact",
            "direction",
            "candidate",
        ),
    )


async def confirm_career_profile_change(
    args: ConfirmCareerProfileChangeArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _scope(ctx)

    def write() -> dict[str, Any]:
        db = SessionLocal()
        try:
            message = _current_user_message(
                db, ctx=ctx, message_id=args.confirmation_message_id
            )
            confirmation = ConfirmationInput(
                kind="conversation_message", source_message_id=message.id
            )
            command = args.command
            if isinstance(command, ProfileFactUpsert):
                profile = career_profile_service.upsert_personal_fact(
                    db,
                    user_pk=user_pk,
                    expected_profile_version=command.expected_profile_version,
                    fact=command.fact,
                    confirmation=confirmation,
                    fact_id=command.fact_id,
                )
                result: dict[str, Any] = {"profile": profile.model_dump(mode="json")}
            elif isinstance(command, ProfileFactRemove):
                profile = career_profile_service.remove_personal_fact(
                    db,
                    user_pk=user_pk,
                    expected_profile_version=command.expected_profile_version,
                    fact_id=command.fact_id,
                    confirmation=confirmation,
                )
                result = {"profile": profile.model_dump(mode="json")}
            elif isinstance(command, ProfileDirectionUpsert):
                profile = career_profile_service.upsert_profile_direction(
                    db,
                    user_pk=user_pk,
                    expected_profile_version=command.expected_profile_version,
                    direction=command.direction,
                    confirmation=confirmation,
                    direction_id=command.direction_id,
                )
                result = {"profile": profile.model_dump(mode="json")}
            elif isinstance(command, ProfileDirectionLifecycle):
                profile = career_profile_service.set_profile_direction_lifecycle(
                    db,
                    user_pk=user_pk,
                    expected_profile_version=command.expected_profile_version,
                    direction_id=command.direction_id,
                    lifecycle=command.lifecycle,
                    confirmation=confirmation,
                )
                result = {"profile": profile.model_dump(mode="json")}
            else:
                career_profile_service.resolve_profile_candidate_items(
                    db,
                    user_pk=user_pk,
                    draft_id=command.draft_id,
                    resolution=CareerProfileCandidateBatchResolutionInput(
                        expected_draft_version=command.expected_draft_version,
                        expected_profile_version=command.expected_profile_version,
                        decisions=command.decisions,
                    ),
                )
                # Candidate status and draft roll-up use guarded bulk updates.
                # Reload the authoritative rows instead of serializing the
                # pre-update identity-map objects returned by the service.
                db.flush()
                db.expire_all()
                result = {
                    "profile": career_profile_service.get_career_profile(
                        db, user_pk=user_pk
                    ).model_dump(mode="json"),
                    "draft": career_profile_service.profile_draft_view(
                        db,
                        user_pk=user_pk,
                        draft_id=command.draft_id,
                    ).model_dump(mode="json"),
                }
            db.commit()
            return {
                **result,
                "confirmation_source": _message_identity(message),
            }
        except Exception as exc:
            db.rollback()
            return _domain_error(exc)
        finally:
            db.close()

    return await asyncio.to_thread(write)


def _profile_resources(
    args: ConfirmCareerProfileChangeArgs, ctx: AgentToolContext
) -> tuple[str, ...]:
    command = args.command
    extra = None
    if isinstance(command, ProfileCandidateResolution):
        extra = f"career_profile_draft:{command.draft_id}"
    return _resource(f"career_profile:user:{ctx.user_pk}", extra)


# ---------------------------------------------------------------------------
# AbilitySignal challenge and source-driven recompute
# ---------------------------------------------------------------------------


class DisputeAbilitySignal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["dispute"]
    signal_id: str = Field(min_length=1, max_length=128)
    expected_version: PositiveInt
    reason: str = Field(min_length=1, max_length=4_000)


class RecomputeInterviewAbilitySignals(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["recompute_interview"]
    interview_record_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=4_000)


AbilityReviewCommand = Annotated[
    DisputeAbilitySignal | RecomputeInterviewAbilitySignals,
    Field(discriminator="operation"),
]


class ReviewAbilitySignalsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_message_id: PositiveInt
    command: AbilityReviewCommand


def _task_authorizes_ability(
    arguments: dict[str, Any],
    ctx: AgentToolContext,
    current_task: str,
) -> bool:
    del ctx
    action_words = {
        "dispute": ("质疑", "纠正", "dispute", "challenge", "correct"),
        "recompute_interview": (
            "重新计算",
            "重算",
            "重新评估",
            "recompute",
            "reassess",
        ),
    }.get(_command_operation(arguments))
    if action_words is None:
        return False
    return _task_explicitly_authorizes(
        current_task,
        action_words=action_words,
        target_words=(
            "能力信号",
            "能力评估",
            "面试能力",
            "ability signal",
            "ability assessment",
            "interview ability",
        ),
    )


async def review_ability_signals(
    args: ReviewAbilitySignalsArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _scope(ctx)

    def write() -> dict[str, Any]:
        db = SessionLocal()
        try:
            message = _current_user_message(
                db, ctx=ctx, message_id=args.confirmation_message_id
            )
            command = args.command
            if isinstance(command, DisputeAbilitySignal):
                signal = ability_signal_service.dispute_ability_signal(
                    db,
                    user_pk=user_pk,
                    signal_id=command.signal_id,
                    expected_version=command.expected_version,
                    reason=command.reason,
                )
                result = {"ability_signal": signal.model_dump(mode="json")}
            else:
                signals = ability_signal_service.project_interview_ability_signals(
                    db,
                    user_pk=user_pk,
                    interview_record_id=command.interview_record_id,
                    force_new_generation=True,
                )
                result = {
                    "ability_signals": [
                        AbilitySignalView.model_validate(item).model_dump(mode="json")
                        for item in signals
                    ],
                    "recomputed_from": {
                        "owner_type": "interview_record",
                        "owner_id": command.interview_record_id,
                    },
                }
            db.commit()
            return {
                **result,
                "confirmation_source": _message_identity(message),
            }
        except Exception as exc:
            db.rollback()
            return _domain_error(exc)
        finally:
            db.close()

    return await asyncio.to_thread(write)


def _ability_resources(
    args: ReviewAbilitySignalsArgs, _ctx: AgentToolContext
) -> tuple[str, ...]:
    command = args.command
    if isinstance(command, DisputeAbilitySignal):
        return (f"ability_signal:{command.signal_id}",)
    return (f"interview_record:{command.interview_record_id}",)


# ---------------------------------------------------------------------------
# NextAction lifecycle, timing and reminders
# ---------------------------------------------------------------------------


class _NextActionDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2_000)
    time_kind: Literal["fixed", "deadline", "flexible"] = "flexible"
    job_opportunity_id: str | None = Field(default=None, max_length=35)
    interview_record_id: str | None = Field(default=None, max_length=128)
    offer_id: str | None = Field(default=None, max_length=35)
    artifact_id: str | None = Field(default=None, max_length=128)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    due_at: AwareDatetime | None = None
    original_time_text: str | None = Field(default=None, max_length=300)
    source_timezone: str | None = Field(default=None, max_length=80)
    reminder_at: AwareDatetime | None = None
    reminder_channel: Literal["in_app"] | None = None

    @model_validator(mode="after")
    def validate_time_shape(self) -> "_NextActionDetails":
        NextActionCreate(
            content=self.content,
            status="planned",
            time_kind=self.time_kind,
            source_kind="user_request",
            source_identity="conversation_message:validation",
            job_opportunity_id=self.job_opportunity_id,
            interview_record_id=self.interview_record_id,
            offer_id=self.offer_id,
            artifact_id=self.artifact_id,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            due_at=self.due_at,
            original_time_text=self.original_time_text,
            source_timezone=self.source_timezone,
            reminder_at=self.reminder_at,
            reminder_channel=self.reminder_channel,
        )
        return self


class CreateNextActionCommand(_NextActionDetails):
    operation: Literal["create"]
    idempotency_key: str = Field(min_length=1, max_length=200)


class EditNextActionCommand(_NextActionDetails):
    operation: Literal["edit"]
    action_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=0)


class PlanNextActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["plan"]
    action_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=0)


class CompleteNextActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["complete"]
    action_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=0)


class CloseNextActionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["close"]
    action_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=300)


NextActionCommand = Annotated[
    CreateNextActionCommand
    | EditNextActionCommand
    | PlanNextActionCommand
    | CompleteNextActionCommand
    | CloseNextActionCommand,
    Field(discriminator="operation"),
]


class ManageNextActionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_message_id: PositiveInt
    command: NextActionCommand


def _task_authorizes_next_action(
    arguments: dict[str, Any],
    ctx: AgentToolContext,
    current_task: str,
) -> bool:
    del ctx
    action_words = {
        "create": (
            "创建",
            "安排",
            "添加",
            "提醒",
            "create",
            "schedule",
            "add",
            "remind",
        ),
        "edit": ("修改", "更新", "调整", "提醒", "edit", "update", "change", "remind"),
        "plan": ("计划", "采纳", "安排", "plan", "accept", "schedule"),
        "complete": ("完成", "标记完成", "complete", "mark done"),
        "close": ("关闭", "取消", "不再推进", "close", "cancel", "drop"),
    }.get(_command_operation(arguments))
    if action_words is None:
        return False
    return _task_explicitly_authorizes(
        current_task,
        action_words=action_words,
        target_words=(
            "下一步",
            "行动",
            "任务",
            "提醒",
            "next action",
            "action",
            "task",
            "reminder",
        ),
    )


def _next_action_details(command: _NextActionDetails) -> dict[str, Any]:
    return {
        "content": command.content,
        "time_kind": command.time_kind,
        "job_opportunity_id": command.job_opportunity_id,
        "interview_record_id": command.interview_record_id,
        "offer_id": command.offer_id,
        "artifact_id": command.artifact_id,
        "starts_at": command.starts_at,
        "ends_at": command.ends_at,
        "due_at": command.due_at,
        "original_time_text": command.original_time_text,
        "source_timezone": command.source_timezone,
        "reminder_at": command.reminder_at,
        "reminder_channel": command.reminder_channel,
    }


def _lock_action_version(db, *, user_pk: int, action_id: str, expected: int) -> None:
    row = (
        db.query(NextAction)
        .filter(NextAction.id == action_id, NextAction.user_id == user_pk)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise CareerObjectNotFoundError(action_id)
    if int(row.version) != expected:
        raise CareerProcessError(
            f"expected action version {expected}, current version is {row.version}"
        )


async def manage_next_action(
    args: ManageNextActionArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _scope(ctx)

    def write() -> dict[str, Any]:
        db = SessionLocal()
        try:
            message = _current_user_message(
                db, ctx=ctx, message_id=args.confirmation_message_id
            )
            source_identity = _message_identity(message)
            source_version = str(message.seq)
            command = args.command
            if isinstance(command, CreateNextActionCommand):
                action = create_next_action(
                    db,
                    user_pk=user_pk,
                    command=NextActionCreate(
                        **_next_action_details(command),
                        status="planned",
                        source_kind="user_request",
                        source_identity=source_identity,
                        source_version=source_version,
                        idempotency_key=command.idempotency_key,
                    ),
                )
            elif isinstance(command, EditNextActionCommand):
                action = edit_next_action(
                    db,
                    user_pk=user_pk,
                    action_id=command.action_id,
                    command=NextActionEdit(
                        **_next_action_details(command),
                        expected_version=command.expected_version,
                    ),
                )
            else:
                _lock_action_version(
                    db,
                    user_pk=user_pk,
                    action_id=command.action_id,
                    expected=command.expected_version,
                )
                transition = NextActionTransition(
                    source_kind="user_assertion",
                    source_identity=source_identity,
                    source_version=source_version,
                )
                if isinstance(command, PlanNextActionCommand):
                    action = plan_next_action(
                        db,
                        user_pk=user_pk,
                        action_id=command.action_id,
                        transition=transition,
                    )
                elif isinstance(command, CompleteNextActionCommand):
                    action = complete_next_action(
                        db,
                        user_pk=user_pk,
                        action_id=command.action_id,
                        transition=transition,
                    )
                else:
                    action = close_next_action(
                        db,
                        user_pk=user_pk,
                        action_id=command.action_id,
                        transition=NextActionClose(
                            **transition.model_dump(), reason=command.reason
                        ),
                    )
            payload = NextActionView.model_validate(action).model_dump(mode="json")
            db.commit()
            return {
                "next_action": payload,
                "confirmation_source": source_identity,
            }
        except Exception as exc:
            db.rollback()
            return _domain_error(exc)
        finally:
            db.close()

    return await asyncio.to_thread(write)


def _next_action_resources(
    args: ManageNextActionArgs, ctx: AgentToolContext
) -> tuple[str, ...]:
    command = args.command
    if isinstance(command, CreateNextActionCommand):
        return _resource(
            f"next_actions:user:{ctx.user_pk}",
            f"job_opportunity:{command.job_opportunity_id}"
            if command.job_opportunity_id
            else None,
        )
    return (f"next_action:{command.action_id}",)


# ---------------------------------------------------------------------------
# Real interview-audio analysis / Debrief entry
# ---------------------------------------------------------------------------


class StartInterviewDebriefArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_message_id: PositiveInt
    audio_file_asset_id: str = Field(min_length=1, max_length=128)
    resume_id: str | None = Field(default=None, min_length=1, max_length=128)
    resume_file_asset_id: str | None = Field(default=None, min_length=1, max_length=128)
    jd_text: str | None = Field(default=None, max_length=100_000)
    jd_file_asset_id: str | None = Field(default=None, min_length=1, max_length=128)
    job_opportunity_id: str | None = Field(default=None, min_length=1, max_length=35)
    language: Literal["zh", "en", "auto"] = "zh"

    @model_validator(mode="after")
    def sources_are_unambiguous(self) -> "StartInterviewDebriefArgs":
        if self.resume_id is not None and self.resume_file_asset_id is not None:
            raise ValueError("provide at most one resume source")
        if self.jd_text and self.jd_file_asset_id is not None:
            raise ValueError("provide at most one JD source")
        return self


def _task_authorizes_interview_debrief(
    arguments: dict[str, Any],
    ctx: AgentToolContext,
    current_task: str,
) -> bool:
    del arguments, ctx
    return _task_explicitly_authorizes(
        current_task,
        action_words=(
            "开始",
            "启动",
            "分析",
            "复盘",
            "转写",
            "start",
            "analyze",
            "review",
            "debrief",
            "transcribe",
        ),
        target_words=(
            "面试录音",
            "面试音频",
            "面试复盘",
            "真实面试",
            "interview recording",
            "interview audio",
            "interview debrief",
        ),
    )


async def _start_interview_debrief_flow(
    args: StartInterviewDebriefArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    from app.services.interview import analysis_intake
    from app.services.interview.interview_record_service import (
        InterviewOpportunityNotFoundError,
    )
    from app.services.uploads.file_asset_service import (
        UPLOAD_STATUS_CONSUMED,
        UPLOAD_STATUS_UPLOADED,
        ensure_uploaded,
        get_owned_file_asset,
    )

    db = SessionLocal()
    try:
        message = _current_user_message(
            db, ctx=ctx, message_id=args.confirmation_message_id
        )
        upload = get_owned_file_asset(
            db,
            file_asset_id=args.audio_file_asset_id,
            user_id=ctx.user_id,
            purpose="interview_audio",
        )
        if upload is None:
            return {"error": "audio_file_asset_not_found_or_not_owned"}
        if upload.upload_status == UPLOAD_STATUS_CONSUMED:
            return {"error": "audio_file_asset_already_consumed"}
        upload = ensure_uploaded(db, upload)
        if upload.upload_status != UPLOAD_STATUS_UPLOADED:
            return {
                "error": "audio_file_asset_not_ready",
                "detail": upload.validation_error or "upload_not_completed",
            }
        try:
            resume_context = await analysis_intake.resolve_resume_context(
                db,
                user_id=ctx.user_id,
                resume_id=args.resume_id,
                resume_file_asset_id=args.resume_file_asset_id,
            )
            jd_text, jd_file_asset_id = await analysis_intake.resolve_jd_context(
                db,
                user_id=ctx.user_id,
                jd_text=args.jd_text,
                jd_file_asset_id=args.jd_file_asset_id,
            )
            record, task = analysis_intake.create_record_and_dispatch(
                db,
                user_id=ctx.user_id,
                upload=upload,
                resume_ctx=resume_context,
                jd_text=jd_text,
                jd_file_asset_id=jd_file_asset_id,
                job_opportunity_id=args.job_opportunity_id,
                language=args.language,
            )
        except analysis_intake.ResumeNotFound as exc:
            db.rollback()
            return {
                "error": "resume_not_found_or_not_owned",
                "reason": str(exc),
            }
        except analysis_intake.ResumeUploadNotFound:
            db.rollback()
            return {"error": "resume_file_asset_not_found_or_not_owned"}
        except InterviewOpportunityNotFoundError:
            db.rollback()
            return {"error": "job_opportunity_not_found_or_not_owned"}
        except Exception as exc:  # durable record may now be terminal failed
            db.rollback()
            logger.warning("Interview debrief dispatch failed (%s)", type(exc).__name__)
            return {
                "error": "interview_analysis_dispatch_failed",
                "analysis_completed": False,
            }
        return {
            "status": "processing",
            "interview_record_id": record.id,
            "background_task_id": task.id,
            "confirmation_source": _message_identity(message),
            "analysis_completed": False,
            "external_action_performed": False,
        }
    except CurrentTurnProofError as exc:
        db.rollback()
        return _domain_error(exc)
    except Exception as exc:  # intake/storage validation boundary
        db.rollback()
        logger.warning("Interview debrief intake failed (%s)", type(exc).__name__)
        return {
            "error": "interview_debrief_intake_failed",
            "analysis_completed": False,
        }
    finally:
        db.close()


async def start_interview_debrief(
    args: StartInterviewDebriefArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    # The whole sync-DB flow lives on one worker thread.  Its async intake
    # helpers may themselves offload bounded document extraction.
    return await asyncio.to_thread(
        lambda: asyncio.run(_start_interview_debrief_flow(args, ctx))
    )


def _interview_debrief_resources(
    args: StartInterviewDebriefArgs, _ctx: AgentToolContext
) -> tuple[str, ...]:
    return _resource(
        f"file_asset:{args.audio_file_asset_id}",
        f"job_opportunity:{args.job_opportunity_id}"
        if args.job_opportunity_id
        else None,
    )


# ---------------------------------------------------------------------------
# Offer comparison (never acceptance, rejection, signature or sending)
# ---------------------------------------------------------------------------


class AnalyzeOffersArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_ids: list[str] = Field(min_length=1, max_length=20)
    base_currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    exchange_rates: list[ExchangeRateAssumption] = Field(default_factory=list)
    tax_assumptions: list[TaxAssumption] = Field(default_factory=list)
    equity_assumptions: list[EquityValuationAssumption] = Field(default_factory=list)
    bonus_assumptions: list[AnnualBonusAssumption] = Field(default_factory=list)
    user_constraints: list[str] = Field(default_factory=list, max_length=50)
    save_artifact: bool = False
    operation_key: str | None = Field(default=None, max_length=128)
    confirmation_message_id: PositiveInt | None = None

    @model_validator(mode="after")
    def validate_analysis(self) -> "AnalyzeOffersArgs":
        OfferAnalysisRequest(**self.model_dump(exclude={"confirmation_message_id"}))
        if self.save_artifact and self.confirmation_message_id is None:
            raise ValueError(
                "saving the comparison requires the current confirmation message"
            )
        if not self.save_artifact and self.confirmation_message_id is not None:
            raise ValueError(
                "confirmation_message_id is only used when save_artifact is true"
            )
        return self


def _task_authorizes_offer_analysis(
    arguments: dict[str, Any],
    ctx: AgentToolContext,
    current_task: str,
) -> bool:
    del ctx
    action_words = (
        ("保存", "存档", "save", "archive")
        if arguments.get("save_artifact")
        else ("比较", "分析", "评估", "compare", "analyze", "assess")
    )
    return _task_explicitly_authorizes(
        current_task,
        action_words=action_words,
        target_words=(
            "offer",
            "录用方案",
            "薪资方案",
            "待遇方案",
            "compensation package",
        ),
    )


async def analyze_offers(
    args: AnalyzeOffersArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _scope(ctx)

    def run() -> dict[str, Any]:
        db = SessionLocal()
        try:
            confirmation = None
            if args.save_artifact:
                assert args.confirmation_message_id is not None
                confirmation = _current_user_message(
                    db, ctx=ctx, message_id=args.confirmation_message_id
                )
            result = offer_analysis_service.compare_offers(
                db,
                user_pk=user_pk,
                command=OfferAnalysisRequest(
                    **args.model_dump(exclude={"confirmation_message_id"})
                ),
            )
            if args.save_artifact:
                db.commit()
            payload = result.model_dump(mode="json")
            return {
                **payload,
                "confirmation_source": (
                    _message_identity(confirmation) if confirmation else None
                ),
                "external_action_performed": False,
                "offer_decision_performed": False,
            }
        except Exception as exc:
            db.rollback()
            return _domain_error(exc)
        finally:
            db.close()

    return await asyncio.to_thread(run)


def _offer_analysis_resources(
    args: AnalyzeOffersArgs, _ctx: AgentToolContext
) -> tuple[str, ...]:
    return tuple(f"offer:{offer_id}" for offer_id in args.offer_ids)


# ---------------------------------------------------------------------------
# PersistentTask definition, state and manual-trigger intake
# ---------------------------------------------------------------------------


class CreatePersistentTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create"]
    title: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1, max_length=5_000)
    trigger: PersistentTaskTriggerSpec
    read_scope: list[str] = Field(default_factory=list, max_length=50)
    action_scope: list[str] = Field(default_factory=list, max_length=50)
    allowed_tool_names: list[str] = Field(default_factory=list, max_length=64)
    skill_ids: list[PositiveInt] = Field(default_factory=list, max_length=20)
    idempotency_key: str = Field(min_length=1, max_length=200)


class EditPersistentTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["edit"]
    task_id: str = Field(min_length=1, max_length=128)
    expected_version: PositiveInt
    title: str | None = Field(default=None, min_length=1, max_length=120)
    instruction: str | None = Field(default=None, min_length=1, max_length=5_000)
    trigger: PersistentTaskTriggerSpec | None = None
    read_scope: list[str] | None = Field(default=None, max_length=50)
    action_scope: list[str] | None = Field(default=None, max_length=50)
    allowed_tool_names: list[str] | None = Field(default=None, max_length=64)
    skill_ids: list[PositiveInt] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def require_change(self) -> "EditPersistentTaskCommand":
        if all(
            value is None
            for value in (
                self.title,
                self.instruction,
                self.trigger,
                self.read_scope,
                self.action_scope,
                self.allowed_tool_names,
                self.skill_ids,
            )
        ):
            raise ValueError("at least one task definition field must change")
        return self


class ChangePersistentTaskStateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["pause", "resume"]
    task_id: str = Field(min_length=1, max_length=128)
    expected_version: PositiveInt


class TriggerPersistentTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["manual_trigger"]
    task_id: str = Field(min_length=1, max_length=128)
    occurred_at: AwareDatetime
    observed_at: AwareDatetime | None = None
    summary: str = Field(min_length=1, max_length=4_000)
    idempotency_key: str = Field(min_length=1, max_length=200)


PersistentTaskCommand = Annotated[
    CreatePersistentTaskCommand
    | EditPersistentTaskCommand
    | ChangePersistentTaskStateCommand
    | TriggerPersistentTaskCommand,
    Field(discriminator="operation"),
]


class ManagePersistentTaskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_message_id: PositiveInt
    command: PersistentTaskCommand


def _task_authorizes_persistent_task(
    arguments: dict[str, Any],
    ctx: AgentToolContext,
    current_task: str,
) -> bool:
    del ctx
    action_words = {
        "create": ("创建", "设置", "create", "set up"),
        "edit": ("修改", "更新", "edit", "update"),
        "pause": ("暂停", "pause"),
        "resume": ("恢复", "继续", "resume", "continue"),
        "manual_trigger": ("运行", "触发", "执行一次", "run", "trigger"),
    }.get(_command_operation(arguments))
    if action_words is None:
        return False
    return _task_explicitly_authorizes(
        current_task,
        action_words=action_words,
        target_words=(
            "持续任务",
            "自动化",
            "定时任务",
            "persistent task",
            "automation",
            "scheduled task",
        ),
    )


def _persistent_task_tools() -> frozenset[str]:
    from app.agent_runtime.turn_tool_catalog import (
        cloud_sustainable_automation_tool_names,
    )

    return cloud_sustainable_automation_tool_names()


async def manage_persistent_task(
    args: ManagePersistentTaskArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _scope(ctx)

    def write() -> dict[str, Any]:
        db = SessionLocal()
        admission = None
        try:
            persistent_tasks = _persistent_tasks()
            message = _current_user_message(
                db, ctx=ctx, message_id=args.confirmation_message_id
            )
            identity = _message_identity(message)
            source_version = str(message.seq)
            command = args.command
            eligible = _persistent_task_tools()
            if isinstance(command, CreatePersistentTaskCommand):
                task = persistent_tasks.create_persistent_task(
                    db,
                    user_pk=user_pk,
                    command=PersistentTaskCreate(
                        title=command.title,
                        instruction=command.instruction,
                        trigger=command.trigger,
                        read_scope=command.read_scope,
                        action_scope=command.action_scope,
                        allowed_tool_names=command.allowed_tool_names,
                        skill_ids=command.skill_ids,
                        user_request_identity=identity,
                        user_request_version=source_version,
                        idempotency_key=command.idempotency_key,
                    ),
                    cloud_sustainable_tool_names=eligible,
                )
                db.commit()
                return {
                    "persistent_task": PersistentTaskView.model_validate(
                        task
                    ).model_dump(mode="json"),
                    "confirmation_source": identity,
                    "future_run_completed": False,
                }
            if isinstance(command, EditPersistentTaskCommand):
                task = persistent_tasks.update_persistent_task(
                    db,
                    user_pk=user_pk,
                    task_id=command.task_id,
                    command=PersistentTaskUpdate(
                        expected_version=command.expected_version,
                        title=command.title,
                        instruction=command.instruction,
                        trigger=command.trigger,
                        read_scope=command.read_scope,
                        action_scope=command.action_scope,
                        allowed_tool_names=command.allowed_tool_names,
                        skill_ids=command.skill_ids,
                        user_request_identity=identity,
                        user_request_version=source_version,
                    ),
                    cloud_sustainable_tool_names=eligible,
                )
                db.commit()
                return {
                    "persistent_task": PersistentTaskView.model_validate(
                        task
                    ).model_dump(mode="json"),
                    "confirmation_source": identity,
                    "future_run_completed": False,
                }
            if isinstance(command, ChangePersistentTaskStateCommand):
                state = "paused" if command.operation == "pause" else "active"
                task = persistent_tasks.change_persistent_task_state(
                    db,
                    user_pk=user_pk,
                    task_id=command.task_id,
                    command=PersistentTaskStateChange(
                        expected_version=command.expected_version,
                        state=state,
                        user_request_identity=identity,
                        user_request_version=source_version,
                    ),
                )
                db.commit()
                return {
                    "persistent_task": PersistentTaskView.model_validate(
                        task
                    ).model_dump(mode="json"),
                    "confirmation_source": identity,
                    "future_run_completed": False,
                }
            admission = persistent_tasks.create_user_confirmed_manual_trigger(
                db,
                user_pk=user_pk,
                task_id=command.task_id,
                command=PersistentTaskTriggerInput(
                    kind="manual",
                    occurred_at=command.occurred_at,
                    observed_at=command.observed_at,
                    source_identity=identity,
                    source_version=source_version,
                    summary=command.summary,
                    idempotency_key=command.idempotency_key,
                ),
                cloud_sustainable_tool_names=eligible,
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            return _domain_error(exc)
        finally:
            db.close()

        assert admission is not None
        dispatch_requested = False
        dispatch_deferred = False
        if admission.should_dispatch and admission.run_request is not None:
            try:
                from app.services.chat.turn_executor import schedule_turn

                dispatch_requested = persistent_tasks.dispatch_automation_run(
                    admission,
                    lambda request: schedule_turn(request.turn_id),
                )
            except Exception:  # durable repair will retry broker dispatch
                dispatch_deferred = True
                logger.exception(
                    "PersistentTask manual-trigger dispatch deferred: %s",
                    admission.turn_id,
                )
        return {
            "trigger_id": admission.trigger_id,
            "status": admission.status,
            "reason": "dispatch_deferred" if dispatch_deferred else admission.reason,
            "turn_id": admission.turn_id,
            "merged_trigger_ids": list(admission.merged_trigger_ids),
            "pending_trigger_count": admission.pending_trigger_count,
            "dispatch_requested": dispatch_requested,
            "dispatch_deferred": dispatch_deferred,
            "run_completed": False,
            "external_action_performed": False,
        }

    return await asyncio.to_thread(write)


def _persistent_task_resources(
    args: ManagePersistentTaskArgs, ctx: AgentToolContext
) -> tuple[str, ...]:
    command = args.command
    if isinstance(command, CreatePersistentTaskCommand):
        return (f"persistent_tasks:user:{ctx.user_pk}",)
    return (f"persistent_task:{command.task_id}",)


# ---------------------------------------------------------------------------
# Exact ArtifactVersion submission assertion (no external execution claim)
# ---------------------------------------------------------------------------


class RecordArtifactSubmissionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_message_id: PositiveInt
    operation_key: str = Field(min_length=1, max_length=128)
    artifact_id: str = Field(min_length=1, max_length=128)
    artifact_version_id: str = Field(min_length=1, max_length=128)
    job_opportunity_id: str = Field(min_length=1, max_length=35)


def _task_authorizes_artifact_submission(
    arguments: dict[str, Any],
    ctx: AgentToolContext,
    current_task: str,
) -> bool:
    del arguments, ctx
    return _task_explicitly_authorizes(
        current_task,
        action_words=(
            "记录",
            "标记",
            "登记",
            "record",
            "mark",
            "log",
        ),
        target_words=(
            "已投递材料",
            "投递版本",
            "已提交材料",
            "简历版本",
            "submitted artifact",
            "submitted version",
            "application material",
            "resume version",
        ),
    )


def _owned_job(
    db,
    user_pk: int,
    owner_type: str,
    job_opportunity_id: str,
) -> bool:
    if owner_type != "job_opportunity":
        return False
    return (
        db.query(JobOpportunity.id)
        .filter(
            JobOpportunity.id == job_opportunity_id,
            JobOpportunity.user_id == user_pk,
        )
        .scalar()
        is not None
    )


async def record_artifact_submission(
    args: RecordArtifactSubmissionArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    user_pk = _scope(ctx)

    def write() -> dict[str, Any]:
        db = SessionLocal()
        try:
            message = _current_user_message(
                db, ctx=ctx, message_id=args.confirmation_message_id
            )
            snapshot: ArtifactSubmissionSnapshot = (
                artifact_service.record_user_confirmed_submission(
                    db,
                    user_pk=user_pk,
                    operation_key=args.operation_key,
                    artifact_id=args.artifact_id,
                    artifact_version_id=args.artifact_version_id,
                    job_opportunity_id=args.job_opportunity_id,
                    confirmation_message_id=message.id,
                    job_owner_checker=_owned_job,
                )
            )
            payload = ArtifactSubmissionView.model_validate(snapshot).model_dump(
                mode="json"
            )
            db.commit()
            return {
                "submission_snapshot": payload,
                "confirmation_source": _message_identity(message),
                "external_action_performed": False,
                "execution_note": (
                    "Recorded the user's assertion about an already submitted exact "
                    "ArtifactVersion; this Tool did not submit or send anything."
                ),
            }
        except Exception as exc:
            db.rollback()
            return _domain_error(exc)
        finally:
            db.close()

    return await asyncio.to_thread(write)


def _artifact_submission_resources(
    args: RecordArtifactSubmissionArgs, _ctx: AgentToolContext
) -> tuple[str, ...]:
    return (
        f"artifact:{args.artifact_id}",
        f"artifact_version:{args.artifact_version_id}",
        f"job_opportunity:{args.job_opportunity_id}",
    )


# ---------------------------------------------------------------------------
# Concrete registrations
# ---------------------------------------------------------------------------


registry.register(
    ToolDefinition(
        name="read_career_domain_state",
        description=(
            "Read bounded owned product state not covered by read_career_context: "
            "reviewable CareerProfile candidates, AbilitySignals, Interview/Debrief "
            "records, current Offers, and PersistentTasks."
        ),
        args_model=ReadCareerDomainStateArgs,
        handler=read_career_domain_state,
        effect=ToolEffect.READ,
        concurrency_safe=True,
        emoji="🗺️",
    )
)

registry.register(
    ToolDefinition(
        name="confirm_career_profile_change",
        description=(
            "Apply one explicit current-user CareerProfile fact/direction edit or "
            "resolve selected existing candidate items through owner and CAS checks."
        ),
        args_model=ConfirmCareerProfileChangeArgs,
        handler=confirm_career_profile_change,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_profile,
        resource_resolver=_profile_resources,
        concurrency_safe=False,
        emoji="👤",
    )
)

registry.register(
    ToolDefinition(
        name="review_ability_signals",
        description=(
            "Dispute one inferred AbilitySignal with CAS, or recompute signals from "
            "an owned InterviewRecord's persisted analysis sources."
        ),
        args_model=ReviewAbilitySignalsArgs,
        handler=review_ability_signals,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_ability,
        resource_resolver=_ability_resources,
        concurrency_safe=False,
        emoji="📈",
    )
)

registry.register(
    ToolDefinition(
        name="manage_next_action",
        description=(
            "Create, CAS-edit, plan, complete, or close an owned durable NextAction; "
            "planned create/edit commands may also schedule an in-app reminder."
        ),
        args_model=ManageNextActionArgs,
        handler=manage_next_action,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_next_action,
        resource_resolver=_next_action_resources,
        concurrency_safe=False,
        emoji="✅",
    )
)

registry.register(
    ToolDefinition(
        name="start_interview_debrief",
        description=(
            "Consume one verified owned interview-audio FileAsset, create the real "
            "InterviewRecord, and dispatch the existing analysis workflow. A returned "
            "processing state is not a completed analysis."
        ),
        args_model=StartInterviewDebriefArgs,
        handler=start_interview_debrief,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_interview_debrief,
        resource_resolver=_interview_debrief_resources,
        concurrency_safe=False,
        emoji="🎧",
    )
)

registry.register(
    ToolDefinition(
        name="analyze_offers",
        description=(
            "Compare owned current Offers with explicit sourced assumptions and "
            "optionally save the report as an Artifact. Never accepts, rejects, "
            "signs, or sends an Offer."
        ),
        args_model=AnalyzeOffersArgs,
        handler=analyze_offers,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_offer_analysis,
        resource_resolver=_offer_analysis_resources,
        concurrency_safe=False,
        emoji="⚖️",
    )
)

registry.register(
    ToolDefinition(
        name="manage_persistent_task",
        description=(
            "Create, CAS-edit, pause, resume, or manually trigger a user-visible "
            "PersistentTask through the canonical automation admission service. "
            "Trigger admission or dispatch never means the run completed."
        ),
        args_model=ManagePersistentTaskArgs,
        handler=manage_persistent_task,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_persistent_task,
        resource_resolver=_persistent_task_resources,
        concurrency_safe=False,
        emoji="⏱️",
    )
)

registry.register(
    ToolDefinition(
        name="record_artifact_submission",
        description=(
            "Record a current-user assertion that one exact owned ArtifactVersion was "
            "already submitted for one owned JobOpportunity. It performs no external "
            "submission and returns no external receipt."
        ),
        args_model=RecordArtifactSubmissionArgs,
        handler=record_artifact_submission,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_artifact_submission,
        resource_resolver=_artifact_submission_resources,
        concurrency_safe=False,
        emoji="📨",
    )
)


__all__ = [
    "AnalyzeOffersArgs",
    "ConfirmCareerProfileChangeArgs",
    "ManageNextActionArgs",
    "ManagePersistentTaskArgs",
    "ReadCareerDomainStateArgs",
    "RecordArtifactSubmissionArgs",
    "ReviewAbilitySignalsArgs",
    "StartInterviewDebriefArgs",
]
