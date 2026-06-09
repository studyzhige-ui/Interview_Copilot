"""Context assembly entry-point for the v3 memory architecture.

Deterministic, no-LLM work (the selection LLM lives in
:func:`app.conversation.query_planner.plan_query`):

  * :func:`load_universal`    — the cheap "every turn" pass: user_profile
                                (full body) + the active ability states
                                (compact) + the learning_strategy one-liner.
  * :func:`attach_active_bodies` — hydrate the full learning_strategy body
                                when the planner asks for it.

Ability states are compact per-topic summaries, so the universal pass loads
them all (capped); there is no per-topic on-demand body to fetch. Only the
learning_strategy doc has a heavier full body gated behind ``load_strategy``.

When the global memory toggle is OFF (Stage-H), the engine bypasses this module
and uses ``V3MemoryContext()`` directly — no cross-session memory at all.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.services.memory import memory_ability_state_service, memory_document_service

logger = logging.getLogger(__name__)

# Mastery label for rendering an ability line.
_MASTERY_LABELS = {"weak": "弱", "improving": "进步中", "stable": "稳定", "strong": "强"}
# Cap ability states injected per turn.
_MAX_ABILITIES = 50


@dataclass
class V3MemoryContext:
    """Bundle of memory artifacts to inject into a chat turn's prompt.

    ``user_profile_body`` and ``ability_states`` load on every turn (both are
    cheap). ``learning_strategy_description`` is the universal-pass one-liner;
    the full ``active_learning_strategy_body`` lands only when the planner asks
    via :func:`attach_active_bodies`.
    """

    user_profile_body: str = ""
    # Active ability states: each {topic, skill_type, mastery_level, summary}.
    ability_states: list[dict] = field(default_factory=list)
    # Universal-pass one-liner for the learning_strategy doc.
    learning_strategy_description: str = ""
    # On-demand full body (set by attach_active_bodies when planner asks).
    active_learning_strategy_body: str = ""

    def render(self) -> str:
        """Render the whole bundle as a single markdown string for injection."""
        parts: list[str] = []

        if self.user_profile_body.strip():
            parts.append("# 用户画像\n" + self.user_profile_body.strip())

        if self.ability_states:
            parts.append("# 能力状态（用户在各主题上的掌握情况）")
            lines = []
            for s in self.ability_states:
                mastery = _MASTERY_LABELS.get(s.get("mastery_level", ""), s.get("mastery_level", "?"))
                lines.append(
                    f"- [{s.get('topic', '')}] {mastery} ({s.get('skill_type', '')})"
                    f" — {s.get('summary', '') or ''}"
                )
            parts.append("\n".join(lines))

        # Strategy: prefer the full body when loaded, else the one-liner.
        if self.active_learning_strategy_body.strip():
            parts.append("# 学习策略详情\n" + self.active_learning_strategy_body.strip())
        elif self.learning_strategy_description.strip():
            parts.append(
                "# 学习策略概览（如需详情，可调相应工具）\n"
                + self.learning_strategy_description.strip()
            )

        return "\n\n".join(parts)


# ──────────────────────────────────────────────────────────────────────


def _ability_states_to_dicts(states) -> list[dict]:
    return [
        {
            "topic": s.topic,
            "skill_type": s.skill_type,
            "mastery_level": s.mastery_level,
            "summary": s.summary or "",
        }
        for s in states[:_MAX_ABILITIES]
    ]


def load_universal(user_id: str) -> V3MemoryContext:
    """The cheap every-turn pass — user_profile FULL + active ability states +
    learning_strategy one-liner. No LLM call; one shared DB session."""
    from app.services.memory._db_helpers import session_scope

    with session_scope(None) as db:
        return V3MemoryContext(
            user_profile_body=memory_document_service.load(user_id, "user_profile", db=db),
            ability_states=_ability_states_to_dicts(
                memory_ability_state_service.load_active(user_id, db=db)
            ),
            learning_strategy_description=memory_document_service.load_description(
                user_id, "learning_strategy", db=db,
            ),
        )


async def attach_active_bodies(
    ctx: V3MemoryContext,
    *,
    user_id: str,
    load_strategy: bool = False,
) -> V3MemoryContext:
    """Hydrate ``ctx`` with the full learning_strategy body if the planner asked.

    Mutates ``ctx`` in place (and returns it). The sync DB read runs in a worker
    thread so the engine's concurrent RAG retrieval keeps making progress.
    """

    def _sync_body() -> V3MemoryContext:
        from app.services.memory._db_helpers import session_scope
        with session_scope(None) as db:
            if load_strategy:
                body = memory_document_service.load(user_id, "learning_strategy", db=db)
                if body and body.strip():
                    ctx.active_learning_strategy_body = body
        return ctx

    return await asyncio.to_thread(_sync_body)


__all__ = [
    "V3MemoryContext",
    "attach_active_bodies",
    "load_universal",
]
