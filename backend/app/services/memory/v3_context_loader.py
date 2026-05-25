"""Context assembly entry-point for the v3 memory architecture.

After the planner-merge refactor the selection LLM lives inside
:func:`app.conversation.query_planner.plan_query` instead of here.
This module only does **deterministic, no-LLM work**:

  * :func:`load_universal`    — the cheap "every turn" pass:
                                   user_profile (full body) + knowledge
                                   index lines + strategy / habit
                                   one-liner descriptions
  * :func:`attach_active_bodies` — given explicit topic names + load
                                   flags from the planner, hydrate
                                   the universal context with the
                                   requested bodies

When the global memory toggle is OFF (Stage-H), the engine bypasses
this module entirely and uses ``V3MemoryContext()`` directly — no
user_profile, no descriptions, no bodies. Privacy mode is "no
cross-session memory at all"; session-local context (recent_turns,
session_state, debrief reference) keeps flowing.

There is no LLM call, no cache, no fallback heuristic — those moved
to the planner. ``V3MemoryContext.render()`` still produces the same
markdown bundle the L1 / L2 strategies inject into their prompts.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.services.memory import (
    habit_doc_service,
    knowledge_doc_service,
    strategy_doc_service,
    user_profile_doc_service,
)

logger = logging.getLogger(__name__)


@dataclass
class V3MemoryContext:
    """Bundle of memory artifacts to inject into a chat turn's prompt.

    Phase A redesign (post planner-merge): only ``user_profile_body``
    is loaded as-is on every turn. The other three memory types expose
    only a one-line description in the universal pass; their full body
    lands in the ``active_*`` fields ONLY when the planner explicitly
    asked for them via :func:`attach_active_bodies`.
    """

    user_profile_body: str = ""

    # Universal-pass descriptions (cheap, every turn).
    knowledge_index_lines: list[str] = field(default_factory=list)
    strategy_description: str = ""
    habit_description: str = ""

    # On-demand bodies (set by attach_active_bodies when the planner
    # asked for them).
    active_knowledge_bodies: dict[str, str] = field(default_factory=dict)
    active_strategy_body: str = ""
    active_habit_body: str = ""

    def render(self) -> str:
        """Render the whole bundle as a single markdown string suitable
        for injection into a system prompt section."""
        parts: list[str] = []

        if self.user_profile_body.strip():
            parts.append("# 用户画像\n" + self.user_profile_body.strip())

        if self.knowledge_index_lines:
            parts.append("# 知识主题索引")
            parts.append("\n".join(self.knowledge_index_lines))

        descriptions: list[str] = []
        if self.strategy_description.strip():
            descriptions.append(f"- 答题策略 doc: {self.strategy_description.strip()}")
        if self.habit_description.strip():
            descriptions.append(f"- 学习习惯 doc: {self.habit_description.strip()}")
        if descriptions:
            parts.append("# 其他记忆 doc 概览（如需详情，可调相应工具）")
            parts.append("\n".join(descriptions))

        if self.active_knowledge_bodies:
            parts.append("# 本次对话相关的知识主题详情")
            for topic, body in self.active_knowledge_bodies.items():
                parts.append(f"## {topic}\n{body.strip()}")
        if self.active_strategy_body.strip():
            parts.append("# 答题策略详情\n" + self.active_strategy_body.strip())
        if self.active_habit_body.strip():
            parts.append("# 学习习惯与心态详情\n" + self.active_habit_body.strip())

        return "\n\n".join(parts)


# ──────────────────────────────────────────────────────────────────────


def load_universal(user_id: str) -> V3MemoryContext:
    """The cheap every-turn pass — user_profile FULL + descriptions
    for the three other memory types. **No LLM call**, just a handful
    of local DB reads (typically tens of ms).

    The planner consumes these descriptions + the topic index to
    decide which bodies (if any) to load on demand.
    """
    return V3MemoryContext(
        user_profile_body=user_profile_doc_service.load(user_id),
        knowledge_index_lines=knowledge_doc_service.list_index_lines(
            user_id, max_topics=50,
        ),
        strategy_description=strategy_doc_service.load_description(user_id),
        habit_description=habit_doc_service.load_description(user_id),
    )


async def attach_active_bodies(
    ctx: V3MemoryContext,
    *,
    user_id: str,
    topics: list[str] | None = None,
    load_strategy: bool = False,
    load_habit: bool = False,
) -> V3MemoryContext:
    """Hydrate ``ctx`` with the bodies the planner asked for.

    Deterministic — no LLM call, no caching. The planner already
    filtered ``topics`` against the live topic index when producing
    the QueryPlan, so we don't re-validate here.

    Mutates ``ctx`` in place (and returns it for chaining). Skips
    bodies whose stored content is empty / whitespace-only so the
    render layer doesn't print blank detail sections.

    Why ``to_thread``: the body underneath is **entirely synchronous**
    DB I/O (each ``knowledge_doc_service.load`` opens a SessionLocal,
    runs a query, closes). Pre-fix this function was ``async def``
    around a sync body — calling it from ``asyncio.create_task`` in
    the engine LOOKED like memory-and-RAG concurrency but actually
    ran serially, because the coroutine never yielded back to the
    loop. ``to_thread`` is the minimal fix: dispatch the sync block
    to a worker thread, let the event loop drive the concurrent
    ``knowledge_task`` in parallel.

    Doing this properly (async DB session per service) is tracked as
    a P2 follow-up — for now the perf win comes from unblocking the
    RAG retrieval, which is by far the heavier of the two.
    """

    def _sync_body() -> V3MemoryContext:
        if topics:
            bodies: dict[str, str] = {}
            for topic in topics:
                doc = knowledge_doc_service.load(user_id, topic)
                if doc and (doc.body or "").strip():
                    bodies[topic] = doc.body
            ctx.active_knowledge_bodies = bodies

        if load_strategy:
            body = strategy_doc_service.load(user_id)
            if body and body.strip():
                ctx.active_strategy_body = body

        if load_habit:
            body = habit_doc_service.load(user_id)
            if body and body.strip():
                ctx.active_habit_body = body

        return ctx

    return await asyncio.to_thread(_sync_body)


__all__ = [
    "V3MemoryContext",
    "attach_active_bodies",
    "load_universal",
]
