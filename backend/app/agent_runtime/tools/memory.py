"""Memory tools for the L2 ReAct agent.

recall_memory  — fetch the v3 memory bundle (universal + on-demand topics).
save_memory    — write a fact into the appropriate v3 doc type.

Both tools target the v3 architecture (knowledge_doc / strategy_doc /
habit_doc / user_profile_doc). The old multi-row ``memory_items`` path
is retired; this module no longer touches that table.
"""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry

logger = logging.getLogger(__name__)


# ── recall_memory ────────────────────────────────────────────────────────


class RecallMemoryArgs(BaseModel):
    """Inspect the user's memory and (optionally) pull specific doc bodies.

    The agent decides what to load itself — no internal selection LLM.
    Pass no args to inspect the universal pass (descriptions only);
    pass explicit ``topics`` / ``load_strategy`` / ``load_habit`` to
    hydrate the requested bodies.
    """
    topics: list[str] = Field(
        default_factory=list,
        description=(
            "Knowledge_doc topic names whose body to pull in. Must be "
            "exact names from the index. Empty = no body loads."
        ),
    )
    load_strategy: bool = Field(
        default=False,
        description="Set true to load the full strategy_doc body.",
    )
    load_habit: bool = Field(
        default=False,
        description="Set true to load the full habit_doc body.",
    )


async def _recall_memory_handler(args: RecallMemoryArgs, ctx: AgentToolContext) -> dict[str, Any]:
    """Return the v3 memory snapshot, optionally with explicit bodies.

    Privacy gate (Stage-H): when the user has the global memory toggle
    OFF for this session, refuse to surface any memory content. The
    tool itself remains in the manifest (so the agent doesn't get
    confused by an asymmetric tool list), but every call returns an
    empty bundle plus an explicit ``disabled`` flag the LLM can see.
    Mirrors Claude Code's ``isAutoMemoryEnabled=false`` shutdown.
    """
    from app.services.memory.recall_policy import (
        is_global_memory_enabled_for_session,
    )
    # Both reads below are sync DB queries; wrap in to_thread so the
    # agent's tool-dispatch await yields the event loop to other
    # in-flight requests during the ~5-50ms it takes.
    enabled = await asyncio.to_thread(
        is_global_memory_enabled_for_session, ctx.session_id, ctx.user_id,
    )
    if not enabled:
        return {
            "disabled": True,
            "reason": (
                "用户已关闭全局记忆开关，本会话不读取跨 session 记忆。"
                "请仅基于本会话上下文回答。"
            ),
            "user_profile": "",
            "knowledge_index": [],
            "strategy_description": "",
            "habit_description": "",
            "active_topics": {},
            "active_strategy": "",
            "active_habit": "",
            "topic_count": 0,
            "active_count": 0,
        }

    from app.services.memory.v3_context_loader import (
        attach_active_bodies,
        load_universal,
    )

    ctx_bundle = await asyncio.to_thread(load_universal, ctx.user_id)
    if args.topics or args.load_strategy or args.load_habit:
        await attach_active_bodies(
            ctx_bundle,
            user_id=ctx.user_id,
            topics=args.topics[:3],
            load_strategy=args.load_strategy,
            load_habit=args.load_habit,
        )
    return {
        "user_profile": ctx_bundle.user_profile_body,
        "knowledge_index": ctx_bundle.knowledge_index_lines,
        "strategy_description": ctx_bundle.strategy_description,
        "habit_description": ctx_bundle.habit_description,
        "active_topics": ctx_bundle.active_knowledge_bodies,
        "active_strategy": ctx_bundle.active_strategy_body,
        "active_habit": ctx_bundle.active_habit_body,
        "topic_count": len(ctx_bundle.knowledge_index_lines),
        "active_count": len(ctx_bundle.active_knowledge_bodies),
    }


# ── save_memory ──────────────────────────────────────────────────────────


class SaveMemoryArgs(BaseModel):
    doc_type: str = Field(
        ...,
        description=(
            "Which memory doc to write to:\n"
            "  - 'knowledge'  — user understanding of a technical/domain topic. "
                              "Requires ``topic`` (e.g. 'Redis', 'TCP').\n"
            "  - 'strategy'   — cross-topic answering methodology.\n"
            "  - 'habit'      — stable practice routine or mindset.\n"
            "  - 'user_profile' — durable identity / preference."
        ),
    )
    topic: str = Field(
        default="",
        description="Required when doc_type='knowledge'. The subject this fact is about.",
    )
    section: str = Field(
        default="",
        description=(
            "Optional ## section name to land the line under. Defaults:\n"
            "  knowledge → '已掌握的认知'\n"
            "  strategy  → '已内化' (for confirmed methods) or '尝试中'\n"
            "  habit     → '稳定的练习节奏' or '心态与应对'"
        ),
    )
    fact: str = Field(
        ..., min_length=1, max_length=1000,
        description="One-line markdown fact to add. Use positive, current-state phrasing.",
    )


_DEFAULT_SECTIONS = {
    "knowledge": "已掌握的认知",
    "strategy": "已内化",
    "habit": "稳定的练习节奏",
}


async def _save_memory_handler(args: SaveMemoryArgs, ctx: AgentToolContext) -> dict[str, Any]:
    """Dispatch one fact into the chosen v3 doc.

    Held under :func:`user_memory_lock` so a save from the ReAct tool
    can't race the realtime-extraction / dreaming writers (which both
    grab the same per-user lock). Patch protocol still defends against
    line-level corruption if the lock degrades to no-op (Redis down).

    Privacy gate (Stage-H): when the global memory toggle is OFF, the
    write is refused. The user explicitly told us they don't want
    cross-session memory built up; an agent tool call sneaking
    through is a privacy bug, not a feature.
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

    from app.services.memory import (
        habit_doc_service,
        knowledge_doc_service,
        strategy_doc_service,
        user_profile_doc_service,
    )
    from app.services.memory._user_memory_lock import user_memory_lock

    doc_type = (args.doc_type or "").strip().lower()
    fact_line = args.fact.strip()
    if not fact_line.startswith("- "):
        fact_line = f"- {fact_line}"

    section = args.section.strip() or _DEFAULT_SECTIONS.get(doc_type, "")

    async with user_memory_lock(ctx.user_id):
        if doc_type == "knowledge":
            topic = (args.topic or "").strip()
            if not topic:
                return {"error": "knowledge doc_type requires a 'topic'"}
            try:
                # apply_patches is sync DB I/O; offload so the async
                # user_memory_lock isn't held across an event-loop-
                # blocking write to Postgres.
                result = await asyncio.to_thread(
                    knowledge_doc_service.apply_patches,
                    user_id=ctx.user_id,
                    topic=topic,
                    patches=[{
                        "op": "add",
                        "section": section,
                        "new_line": fact_line,
                    }],
                    change_type="patch_realtime",
                    source_session_id=ctx.session_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("save_memory knowledge failed: %s", exc)
                return {"error": f"failed: {exc}"}
            return {
                "doc_type": "knowledge",
                "topic": topic,
                "applied": result.applied,
                "dropped": result.dropped,
                "skipped": result.skipped,
            }

        if doc_type in {"strategy", "habit"}:
            service = strategy_doc_service if doc_type == "strategy" else habit_doc_service
            try:
                result = await asyncio.to_thread(
                    service.apply_patches,
                    user_id=ctx.user_id,
                    patches=[{
                        "op": "add",
                        "section": section,
                        "new_line": fact_line,
                    }],
                    change_type="patch_realtime",
                    source_session_id=ctx.session_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("save_memory %s failed: %s", doc_type, exc)
                return {"error": f"failed: {exc}"}
            return {
                "doc_type": doc_type,
                "applied": result.applied,
                "dropped": result.dropped,
                "skipped": result.skipped,
            }

        if doc_type == "user_profile":
            try:
                stats = await asyncio.to_thread(
                    user_profile_doc_service.apply_patches,
                    ctx.user_id,
                    [{"op": "add", "new_line": fact_line}],
                    change_type="patch_realtime",
                    source_session_id=ctx.session_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("save_memory user_profile failed: %s", exc)
                return {"error": f"failed: {exc}"}
            return {"doc_type": "user_profile", **stats}

        return {
            "error": f"unknown doc_type: {doc_type}",
            "valid": ["knowledge", "strategy", "habit", "user_profile"],
        }


# ── Registration ─────────────────────────────────────────────────────────

registry.register(ToolEntry(
    name="recall_memory",
    description=(
        "Recall user's long-term memory. Returns the v3 bundle: "
        "user_profile + knowledge topic index + selected topic bodies + "
        "strategy + habit. Use to ground responses in what you know about "
        "this user and what they've previously learned / committed to."
    ),
    args_model=RecallMemoryArgs,
    handler=_recall_memory_handler,
    max_result_chars=20000,
    emoji="🧠",
))

registry.register(ToolEntry(
    name="save_memory",
    description=(
        "Save one fact to the user's long-term memory. Pick doc_type "
        "carefully — 'knowledge' for topic-specific understanding "
        "(requires topic name), 'strategy' for answering methodology, "
        "'habit' for stable practice/mindset, 'user_profile' for identity "
        "facts. Use positive present-state phrasing (not past errors)."
    ),
    args_model=SaveMemoryArgs,
    handler=_save_memory_handler,
    max_result_chars=2000,
    emoji="💾",
))
