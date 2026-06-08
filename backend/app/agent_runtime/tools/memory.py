"""Memory tools for the L2 ReAct agent.

recall_memory  — fetch the v3 memory bundle (user_profile + ability states +
                 learning_strategy, optionally the full strategy body).
save_memory    — write into one of the three v3 surfaces: ability_state
                 (per-topic mastery), user_profile, or learning_strategy.
"""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry

logger = logging.getLogger(__name__)


# ── recall_memory ────────────────────────────────────────────────────────


class RecallMemoryArgs(BaseModel):
    """Inspect the user's memory. The user_profile and active ability states are
    always returned; set ``load_strategy`` to also pull the full
    learning_strategy body (its one-liner is always included)."""

    load_strategy: bool = Field(
        default=False,
        description="Set true to load the full learning_strategy doc body.",
    )


def _disabled_bundle() -> dict[str, Any]:
    return {
        "disabled": True,
        "reason": (
            "用户已关闭全局记忆开关，本会话不读取跨 session 记忆。"
            "请仅基于本会话上下文回答。"
        ),
        "user_profile": "",
        "ability_states": [],
        "learning_strategy_description": "",
        "active_learning_strategy": "",
        "ability_count": 0,
    }


async def _recall_memory_handler(args: RecallMemoryArgs, ctx: AgentToolContext) -> dict[str, Any]:
    """Return the v3 memory snapshot, optionally with the full strategy body.

    Privacy gate (Stage-H): when the global memory toggle is OFF for this
    session, every call returns an empty bundle plus a ``disabled`` flag.
    """
    from app.services.memory.recall_policy import (
        is_global_memory_enabled_for_session,
    )
    enabled = await asyncio.to_thread(
        is_global_memory_enabled_for_session, ctx.session_id, ctx.user_id,
    )
    if not enabled:
        return _disabled_bundle()

    from app.services.memory.v3_context_loader import (
        attach_active_bodies,
        load_universal,
    )

    bundle = await asyncio.to_thread(load_universal, ctx.user_id)
    if args.load_strategy:
        await attach_active_bodies(bundle, user_id=ctx.user_id, load_strategy=True)
    return {
        "user_profile": bundle.user_profile_body,
        "ability_states": bundle.ability_states,
        "learning_strategy_description": bundle.learning_strategy_description,
        "active_learning_strategy": bundle.active_learning_strategy_body,
        "ability_count": len(bundle.ability_states),
    }


# ── save_memory ──────────────────────────────────────────────────────────


class SaveMemoryArgs(BaseModel):
    target: str = Field(
        ...,
        description=(
            "Which memory surface to write:\n"
            "  - 'ability_state'     — user's mastery of a specific topic. "
                                     "Requires topic + skill_type + mastery_level + summary.\n"
            "  - 'user_profile'      — durable identity / preference / goal. Requires fact.\n"
            "  - 'learning_strategy' — answering / review / training method. Requires fact."
        ),
    )
    # ability_state fields
    topic: str = Field(default="", description="ability_state: the subject, e.g. 'Redis 缓存穿透'.")
    skill_type: str = Field(
        default="",
        description=(
            "ability_state: one of knowledge_topic / system_design / behavioral / "
            "communication / project_deep_dive."
        ),
    )
    mastery_level: str = Field(
        default="",
        description="ability_state: one of weak / improving / stable / strong.",
    )
    summary: str = Field(
        default="",
        description="ability_state: one-line current-state description (not past errors).",
    )
    # user_profile / learning_strategy fields
    section: str = Field(
        default="",
        description="user_profile/learning_strategy: optional ## section name for the line.",
    )
    fact: str = Field(
        default="",
        max_length=1000,
        description="user_profile/learning_strategy: one-line markdown fact to add.",
    )


async def _save_memory_handler(args: SaveMemoryArgs, ctx: AgentToolContext) -> dict[str, Any]:
    """Dispatch one fact into the chosen v3 surface.

    Held under :func:`user_memory_lock` so it can't race the realtime-extraction
    / dreaming writers. Privacy gate (Stage-H): refused when the global memory
    toggle is OFF.
    """
    from app.services.memory.recall_policy import (
        is_global_memory_enabled_for_session,
    )
    enabled = await asyncio.to_thread(
        is_global_memory_enabled_for_session, ctx.session_id, ctx.user_id,
    )
    if not enabled:
        return {
            "disabled": True,
            "reason": (
                "用户已关闭全局记忆开关，禁止写入跨 session 记忆。"
                "如需启用，请到「个人中心」打开全局记忆开关。"
            ),
        }

    from app.services.memory import memory_document_service
    from app.services.memory._user_memory_lock import user_memory_lock

    target = (args.target or "").strip().lower()

    async with user_memory_lock(ctx.user_id):
        if target == "ability_state":
            return await asyncio.to_thread(_save_ability_state, args, ctx)

        if target in {"user_profile", "learning_strategy"}:
            fact_line = args.fact.strip()
            if not fact_line:
                return {"error": f"{target} requires a 'fact'"}
            if not fact_line.startswith("- "):
                fact_line = f"- {fact_line}"
            patch: dict[str, Any] = {"op": "add", "new_line": fact_line}
            if args.section.strip():
                patch["section"] = args.section.strip()
            try:
                result = await asyncio.to_thread(
                    memory_document_service.apply_patches,
                    ctx.user_id, target, [patch],
                    change_type="patch_realtime",
                    source_conversation_id=ctx.session_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("save_memory %s failed: %s", target, exc)
                return {"error": f"failed: {exc}"}
            return {
                "target": target,
                "applied": result.applied,
                "dropped": result.dropped,
                "skipped": result.skipped,
            }

        return {
            "error": f"unknown target: {target}",
            "valid": ["ability_state", "user_profile", "learning_strategy"],
        }


def _save_ability_state(args: SaveMemoryArgs, ctx: AgentToolContext) -> dict[str, Any]:
    from app.services.memory import memory_ability_state_service
    from app.models.memory_ability_state import MASTERY_LEVELS, SKILL_TYPES

    topic = args.topic.strip()
    skill_type = args.skill_type.strip()
    mastery_level = args.mastery_level.strip()
    if not topic:
        return {"error": "ability_state requires a 'topic'"}
    if skill_type not in SKILL_TYPES:
        return {"error": f"skill_type must be one of {list(SKILL_TYPES)}"}
    if mastery_level not in MASTERY_LEVELS:
        return {"error": f"mastery_level must be one of {list(MASTERY_LEVELS)}"}
    try:
        memory_ability_state_service.upsert(
            ctx.user_id,
            topic=topic, skill_type=skill_type, mastery_level=mastery_level,
            summary=args.summary.strip() or None,
            change_type="patch_realtime",
            source_conversation_id=ctx.session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("save_memory ability_state failed: %s", exc)
        return {"error": f"failed: {exc}"}
    return {"target": "ability_state", "topic": topic, "mastery_level": mastery_level}


# ── Registration ─────────────────────────────────────────────────────────

registry.register(ToolEntry(
    name="recall_memory",
    description=(
        "Recall the user's long-term memory: user_profile + per-topic ability "
        "states (what they're weak/strong at) + learning_strategy. Use to ground "
        "responses in what you know about this user and how they're progressing."
    ),
    args_model=RecallMemoryArgs,
    handler=_recall_memory_handler,
    max_result_chars=20000,
    emoji="🧠",
))

registry.register(ToolEntry(
    name="save_memory",
    description=(
        "Save one fact to the user's long-term memory. Pick target: "
        "'ability_state' for a topic's mastery (needs topic/skill_type/"
        "mastery_level/summary), 'user_profile' for identity/preference, "
        "'learning_strategy' for answering/review methodology. Use positive "
        "present-state phrasing (not past errors)."
    ),
    args_model=SaveMemoryArgs,
    handler=_save_memory_handler,
    max_result_chars=2000,
    emoji="💾",
))
