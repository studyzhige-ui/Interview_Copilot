"""Explicit guidance commands routed to their three existing owners."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, ToolDefinition, registry
from app.db.database import SessionLocal
from app.models.chat import Conversation
from app.schemas.personalization import CopilotPreferenceUpdate, ScopedGuidanceUpdate
from app.services import personalization_service
from app.services.chat.current_turn_source import (
    CurrentTurnSourceError,
    require_current_turn_user_message,
)

GuidanceOperation = Literal[
    "set_conversation",
    "clear_conversation",
    "set_debrief",
    "clear_debrief",
    "add_global_rule",
    "remove_global_rule",
]


class ManageGuidanceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: GuidanceOperation
    expected_version: int = Field(ge=0)
    source_message_id: PositiveInt
    guidance: str | None = Field(default=None, max_length=4_000)
    rule: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_operation_payload(self) -> "ManageGuidanceArgs":
        if self.operation.startswith("set_"):
            if not (self.guidance or "").strip() or self.rule is not None:
                raise ValueError("set operation requires guidance only")
        elif self.operation.startswith("clear_"):
            if self.guidance is not None or self.rule is not None:
                raise ValueError("clear operation accepts no guidance or rule")
        elif not (self.rule or "").strip() or self.guidance is not None:
            raise ValueError("global rule operation requires rule only")
        return self


async def _manage_guidance_handler(
    args: ManageGuidanceArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    return await asyncio.to_thread(_manage_guidance_sync, args, ctx)


def _manage_guidance_sync(
    args: ManageGuidanceArgs,
    ctx: AgentToolContext,
) -> dict[str, Any]:
    if ctx.user_pk is None or ctx.user_pk <= 0:
        return {"error": "personalization_user_scope_unavailable"}
    db = SessionLocal()
    try:
        message = require_current_turn_user_message(
            db,
            user_pk=ctx.user_pk,
            turn_id=ctx.turn_id,
            conversation_id=ctx.session_id,
            message_id=args.source_message_id,
        )
        if args.operation in {"set_conversation", "clear_conversation"}:
            view = personalization_service.update_conversation_guidance(
                db,
                user_pk=ctx.user_pk,
                conversation_id=ctx.session_id,
                command=ScopedGuidanceUpdate(
                    expected_version=args.expected_version,
                    guidance=(args.guidance or "").strip()
                    if args.operation == "set_conversation"
                    else None,
                    source_message_id=(
                        message.id if args.operation == "set_conversation" else None
                    ),
                ),
            )
            owner = "conversation"
        elif args.operation in {"set_debrief", "clear_debrief"}:
            conversation = (
                db.query(Conversation)
                .filter(
                    Conversation.id == ctx.session_id,
                    Conversation.user_id == ctx.user_pk,
                    Conversation.subject_type == "interview_record",
                    Conversation.subject_id.is_not(None),
                )
                .one_or_none()
            )
            if conversation is None:
                return {"error": "current_conversation_is_not_a_debrief"}
            view = personalization_service.update_debrief_guidance(
                db,
                user_pk=ctx.user_pk,
                interview_record_id=str(conversation.subject_id),
                command=ScopedGuidanceUpdate(
                    expected_version=args.expected_version,
                    guidance=(args.guidance or "").strip()
                    if args.operation == "set_debrief"
                    else None,
                    source_message_id=(
                        message.id if args.operation == "set_debrief" else None
                    ),
                ),
            )
            owner = "interview_record"
        else:
            current = personalization_service.get_copilot_preference(
                db,
                user_pk=ctx.user_pk,
            )
            if current.version != args.expected_version:
                raise personalization_service.PersonalizationConflictError(
                    "CopilotPreference version changed"
                )
            rule = (args.rule or "").strip()
            instructions = list(current.instructions)
            if args.operation == "add_global_rule":
                if rule not in instructions:
                    instructions.append(rule)
            else:
                if rule not in instructions:
                    return {"error": "global_rule_not_found"}
                instructions.remove(rule)
            view = personalization_service.replace_copilot_preference(
                db,
                user_pk=ctx.user_pk,
                command=CopilotPreferenceUpdate(
                    expected_version=args.expected_version,
                    instructions=instructions,
                ),
            )
            owner = "copilot_preference"
        db.commit()
        return {
            "owner": owner,
            "operation": args.operation,
            "state": view.model_dump(mode="json"),
            "source_message_id": message.id,
        }
    except CurrentTurnSourceError as exc:
        db.rollback()
        return {"error": "current_task_confirmation_required", "detail": str(exc)}
    except personalization_service.PersonalizationConflictError as exc:
        db.rollback()
        return {"error": "version_conflict", "detail": str(exc)}
    except personalization_service.PersonalizationNotFoundError:
        db.rollback()
        return {"error": "not_found_or_not_owned"}
    finally:
        db.close()


_QUESTION_CUES = ("如何", "怎么", "是否", "能否", "how ", "should ", "can ")
_NEGATION_CUES = ("不要", "别", "取消这个要求", "do not", "don't", "not ")
_SET_CUES = (
    "设为",
    "设置",
    "记住",
    "采用",
    "使用",
    "都要",
    "请",
    "set",
    "remember",
    "use",
)
_CLEAR_CUES = ("清除", "取消", "删除", "不再", "clear", "remove", "forget")
_CONVERSATION_CUES = (
    "这个对话",
    "本对话",
    "当前对话",
    "这个聊天",
    "this chat",
    "this conversation",
)
_DEBRIEF_CUES = (
    "本次复盘",
    "这次复盘",
    "本次面试复盘",
    "this debrief",
    "this interview review",
)
_GLOBAL_CUES = (
    "以后",
    "默认",
    "每次",
    "所有对话",
    "全局",
    "from now on",
    "by default",
    "always",
    "all conversations",
)


def _task_authorizes_guidance(
    arguments: dict[str, Any],
    _ctx: AgentToolContext,
    current_task: str,
) -> bool:
    task = " ".join(str(current_task or "").casefold().split())
    if not task or any(cue in task for cue in _QUESTION_CUES):
        return False
    operation = str(arguments.get("operation") or "")
    if operation.startswith("set_") or operation == "add_global_rule":
        if any(cue in task for cue in _NEGATION_CUES):
            return False
        action_cues = (
            (*_SET_CUES, *_GLOBAL_CUES) if operation == "add_global_rule" else _SET_CUES
        )
    else:
        action_cues = _CLEAR_CUES
    if not any(cue in task for cue in action_cues):
        return False
    if operation.endswith("conversation"):
        return any(cue in task for cue in _CONVERSATION_CUES)
    if operation.endswith("debrief"):
        return any(cue in task for cue in _DEBRIEF_CUES)
    return any(cue in task for cue in _GLOBAL_CUES)


def _guidance_resources(
    args: ManageGuidanceArgs,
    ctx: AgentToolContext,
) -> tuple[str, ...]:
    if args.operation in {"add_global_rule", "remove_global_rule"}:
        return (f"user:{ctx.user_pk}:copilot-preference",)
    return (f"conversation:{ctx.session_id}:guidance",)


registry.register(
    ToolDefinition(
        name="manage_personalization_guidance",
        description=(
            "Set or clear explicit guidance for this Conversation, the current "
            "InterviewRecord debrief, or a user-confirmed global default. "
            "Never stores inferred behavior or Long-term Memory."
        ),
        args_model=ManageGuidanceArgs,
        handler=_manage_guidance_handler,
        effect=ToolEffect.INTERNAL_WRITE,
        task_authorizer=_task_authorizes_guidance,
        resource_resolver=_guidance_resources,
        concurrency_safe=False,
        emoji="⚙️",
    )
)


__all__ = ["ManageGuidanceArgs"]
