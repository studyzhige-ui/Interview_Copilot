"""Memory tools for the L2 ReAct agent.

recall_memory  — fetch the v3 memory bundle (universal + on-demand topics).
save_memory    — write a fact into the appropriate v3 doc type.

Both tools target the v3 architecture (knowledge_doc / strategy_doc /
habit_doc / user_profile_doc). The old multi-row ``memory_items`` path
is retired; this module no longer touches that table.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry

logger = logging.getLogger(__name__)


# ── recall_memory ────────────────────────────────────────────────────────


class RecallMemoryArgs(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=500,
        description="Free-text query — drives the selection LLM that picks "
                    "which knowledge_doc topic bodies to surface.",
    )
    max_topics: int = Field(
        default=3, ge=1, le=5,
        description="Max knowledge_doc topic bodies to pull in on-demand.",
    )


async def _recall_memory_handler(args: RecallMemoryArgs, ctx: AgentToolContext) -> dict[str, Any]:
    """Return the v3 memory snapshot tailored to ``query``."""
    from app.services.memory.v3_context_loader import load_with_active_bodies

    ctx_bundle = await load_with_active_bodies(
        ctx.user_id,
        query=args.query,
        max_active_topics=args.max_topics,
    )
    return {
        "user_profile": ctx_bundle.user_profile_body,
        "knowledge_index": ctx_bundle.knowledge_index_lines,
        "active_topics": ctx_bundle.active_knowledge_bodies,
        "strategy": ctx_bundle.strategy_body,
        "habit": ctx_bundle.habit_body,
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
    """
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
                result = knowledge_doc_service.apply_patches(
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
                result = service.apply_patches(
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
                stats = user_profile_doc_service.apply_patches(
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
