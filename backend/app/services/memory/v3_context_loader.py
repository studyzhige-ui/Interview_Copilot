"""Context assembly entry-point for the v3 memory architecture.

Loads the four memory artifacts for an LLM call in two passes:

  1. **Cheap pass** (always): user_profile (full body) + knowledge_doc
     index + strategy doc + habit doc. ~5-10 KB. Loaded for every
     turn including casual / non-domain chat — universal context.

  2. **On-demand pass** (when query is domain-relevant): the bodies of
     up to N knowledge_doc topics the LLM picks via
     ``CONTEXT_SELECTION_PROMPT``.

Why we don't auto-load all knowledge_doc bodies
-----------------------------------------------
A user with 30+ topics produces ~50KB of bodies; loading all of that
into every chat turn would balloon the prompt cache key and waste
tokens on irrelevant topics. The selection LLM is cheap (one tiny
JSON call) and lets the prompt stay focused.

For "general" or non-domain sessions (user asks "today's weather?"),
the selection pass returns `[]` and no bodies load. Domain doc index
+ user_profile + strategy + habit are still in context — they're
small and provide personalisation universally.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.rag.embeddings import agent_fast_llm
from app.services.memory import (
    habit_doc_service,
    knowledge_doc_service,
    strategy_doc_service,
    user_profile_doc_service,
)
from app.services.memory._metrics import incr as _metric_incr
from app.services.memory.prompts import CONTEXT_SELECTION_PROMPT

logger = logging.getLogger(__name__)


# ── Selection LLM hardening ───────────────────────────────────────────
# Hard upper bound on how long we wait for the selection LLM. Beyond
# this the chat turn proceeds on the deterministic fallback. Should
# be << total chat-turn latency budget.
SELECTION_LLM_TIMEOUT_SEC = 2.5

# Cache window for selection results. The most common pattern is the user
# asking a follow-up that picks the same topics; caching for a minute
# avoids paying the selection LLM cost on every keystroke-driven turn.
_SELECTION_CACHE_TTL_SEC = 60.0
# Cache value is a SelectionDecision (defined below). Key includes a
# fingerprint of the index_lines so a new topic added by realtime
# extraction WITHIN the 60s window invalidates the cache for any
# affected user-query pair (review F-H3).
_SELECTION_CACHE: dict[tuple[str, str, int, int], tuple[float, "SelectionDecision"]] = {}
_SELECTION_CACHE_MAX_ENTRIES = 512


@dataclass(frozen=True)
class SelectionDecision:
    """What the selection LLM decided to load for the current turn."""
    knowledge_topics: tuple[str, ...] = ()
    load_strategy: bool = False
    load_habit: bool = False


@dataclass
class V3MemoryContext:
    """Bundle of memory artifacts to inject into a chat turn's prompt.

    Phase A redesign: only ``user_profile_body`` is loaded as-is on
    every turn. The other three memory types expose only a one-line
    description in the universal pass; their full body lands in the
    ``active_*`` fields ONLY when the selection LLM decides to load
    them for this query.
    """

    user_profile_body: str = ""

    # Universal-pass descriptions (cheap, every turn).
    knowledge_index_lines: list[str] = field(default_factory=list)
    strategy_description: str = ""
    habit_description: str = ""

    # On-demand bodies (only set when selection LLM said load=True).
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

        # Strategy / habit DESCRIPTIONS (one-liners). Only the active
        # bodies, if pulled, get rendered in full below.
        descriptions: list[str] = []
        if self.strategy_description.strip():
            descriptions.append(f"- 答题策略 doc: {self.strategy_description.strip()}")
        if self.habit_description.strip():
            descriptions.append(f"- 学习习惯 doc: {self.habit_description.strip()}")
        if descriptions:
            parts.append("# 其他记忆 doc 概览（如需详情，可调相应工具）")
            parts.append("\n".join(descriptions))

        # On-demand bodies (selection LLM decided to load).
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


def load_profile_only(user_id: str) -> V3MemoryContext:
    """Minimal context for sessions where memory recall is OFF.

    Privacy-conscious users who toggle recall off expect their
    interview prep notes to NOT leak into the LLM context. We still
    load the user_profile though — without it the AI calls them by
    the wrong name etc. That's basic identity, not interview prep
    history, so it's defensible to keep.
    """
    return V3MemoryContext(
        user_profile_body=user_profile_doc_service.load(user_id),
    )


def load_universal(user_id: str) -> V3MemoryContext:
    """Cheap pass (Phase A) — user_profile FULL + descriptions only for
    the three other memory types. No LLM call.

    The strategy/habit/knowledge bodies are NOT loaded here; the
    selection LLM in ``load_with_active_bodies`` picks which to pull
    in for the current query. This mirrors Claude Code's "show the
    description, let the LLM ask for content" pattern.
    """
    return V3MemoryContext(
        user_profile_body=user_profile_doc_service.load(user_id),
        knowledge_index_lines=knowledge_doc_service.list_index_lines(
            user_id, max_topics=50,
        ),
        strategy_description=strategy_doc_service.load_description(user_id),
        habit_description=habit_doc_service.load_description(user_id),
    )


async def load_with_active_bodies(
    user_id: str,
    *,
    query: str,
    max_active_topics: int = 3,
) -> V3MemoryContext:
    """Universal pass + on-demand bodies decided by the selection LLM.

    Phase A: the selection LLM picks among ALL three non-profile doc
    types (knowledge topics + strategy + habit), not just knowledge.

    Returns a context with whichever bodies the LLM/fallback marked as
    relevant. Never silently drops the universal pass — even on
    selection failure the user_profile + description layer is still
    present.
    """
    ctx = load_universal(user_id)

    if not (query or "").strip():
        return ctx

    decision = await _select_active_memory(
        user_id=user_id,
        query=query,
        index_lines=ctx.knowledge_index_lines,
        strategy_description=ctx.strategy_description,
        habit_description=ctx.habit_description,
        max_topics=max_active_topics,
    )

    # Knowledge bodies
    if decision.knowledge_topics:
        bodies: dict[str, str] = {}
        for topic in decision.knowledge_topics:
            doc = knowledge_doc_service.load(user_id, topic)
            if doc and (doc.body or "").strip():
                bodies[topic] = doc.body
        ctx.active_knowledge_bodies = bodies

    # Strategy body
    if decision.load_strategy:
        body = strategy_doc_service.load(user_id)
        if body.strip():
            ctx.active_strategy_body = body

    # Habit body
    if decision.load_habit:
        body = habit_doc_service.load(user_id)
        if body.strip():
            ctx.active_habit_body = body

    return ctx


# ──────────────────────────────────────────────────────────────────────
# Selection LLM
# ──────────────────────────────────────────────────────────────────────


async def _select_active_memory(
    *,
    user_id: str,
    query: str,
    index_lines: list[str],
    strategy_description: str,
    habit_description: str,
    max_topics: int,
) -> SelectionDecision:
    """Ask the fast LLM which docs to load; on any failure or timeout,
    fall back to a deterministic heuristic.

    Hardening (Checkpoint 3, F3+F8 — preserved from prior design):

    * **Cache** results per ``(user_id, lowercased query, max_topics)``
      for 60s — follow-up questions usually want the same docs.
    * **Timeout** the LLM call at ``SELECTION_LLM_TIMEOUT_SEC``.
    * **Fallback** on any LLM failure:
        - knowledge: top-N by last_discussed_at
        - strategy / habit: load=True iff the user has a non-empty doc
          (cheap, never wrong: at worst we load a doc the user
          didn't strictly need this turn).
    * **Metric** ``memory.selection_llm_failed`` per failure.
    """
    # Hash the index_lines into the cache key so a new knowledge topic
    # added by realtime extraction WITHIN the 60s TTL window
    # invalidates this cache entry — otherwise the second turn would
    # silently get the stale topic set even though the LLM would now
    # have a new candidate to pick.
    cache_key = (
        user_id,
        (query or "").strip().lower(),
        max_topics,
        hash(tuple(index_lines)),
    )
    now = time.monotonic()
    cached = _SELECTION_CACHE.get(cache_key)
    if cached is not None:
        expiry, decision = cached
        if expiry > now:
            return decision
        _SELECTION_CACHE.pop(cache_key, None)

    indexed_names = {_extract_topic_name(line) for line in index_lines}
    indexed_names.discard("")

    fallback_reason: str | None = None

    prompt = CONTEXT_SELECTION_PROMPT.format(
        knowledge_index="\n".join(index_lines) or "（暂无主题）",
        strategy_description=strategy_description or "（空）",
        habit_description=habit_description or "（空）",
        query=query.strip(),
    )
    try:
        response = await asyncio.wait_for(
            agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            ),
            timeout=SELECTION_LLM_TIMEOUT_SEC,
        )
        raw = str(response.text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw) if raw else {}
        if not isinstance(parsed, dict):
            raise ValueError("selection LLM payload was not a JSON object")

        topics_raw = parsed.get("knowledge_topics") or []
        if not isinstance(topics_raw, list):
            raise ValueError("knowledge_topics was not a list")
        topics = tuple(
            t for t in topics_raw if isinstance(t, str) and t in indexed_names
        )[:max_topics]

        decision = SelectionDecision(
            knowledge_topics=topics,
            load_strategy=bool(parsed.get("load_strategy", False)),
            load_habit=bool(parsed.get("load_habit", False)),
        )
        _cache_selection(cache_key, decision)
        return decision
    except asyncio.TimeoutError:
        fallback_reason = "timeout"
        logger.warning(
            "v3_context_loader: selection LLM timed out after %.2fs; "
            "falling back to deterministic heuristic",
            SELECTION_LLM_TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001
        fallback_reason = type(exc).__name__
        logger.warning(
            "v3_context_loader: selection LLM failed (%s); "
            "falling back to deterministic heuristic",
            exc,
        )

    _metric_incr(
        "memory.selection_llm_failed",
        user_id=user_id,
        reason=fallback_reason,
    )

    # Deterministic fallback: most-recently-discussed knowledge topics +
    # load strategy/habit iff the user actually has a non-empty doc.
    # We prefer "load doc the user didn't strictly need this turn" over
    # "drop all memory because the helper LLM died" — chat quality
    # should degrade gracefully.
    fallback_topics = tuple(
        t for t in _fallback_recent_topics(user_id, max_topics=max_topics)
        if t in indexed_names
    )
    fallback = SelectionDecision(
        knowledge_topics=fallback_topics,
        load_strategy=bool(strategy_description.strip()),
        load_habit=bool(habit_description.strip()),
    )
    _cache_selection(cache_key, fallback)
    return fallback


def _cache_selection(
    key: tuple[str, str, int, int], decision: SelectionDecision,
) -> None:
    """Insert a cache entry. Cheap LRU-by-insertion-order eviction
    keeps the dict bounded; we don't care about strict LRU semantics
    since entries TTL out in 60s anyway."""
    if len(_SELECTION_CACHE) >= _SELECTION_CACHE_MAX_ENTRIES:
        try:
            oldest = next(iter(_SELECTION_CACHE))
            _SELECTION_CACHE.pop(oldest, None)
        except StopIteration:
            pass
    _SELECTION_CACHE[key] = (
        time.monotonic() + _SELECTION_CACHE_TTL_SEC, decision,
    )


def _fallback_recent_topics(user_id: str, *, max_topics: int) -> list[str]:
    """Top-N knowledge_doc topics by ``last_discussed_at`` DESC. Used
    when the selection LLM fails — better than returning zero bodies."""
    try:
        docs = knowledge_doc_service.load_all(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("v3_context_loader: fallback recent topics failed: %s", exc)
        return []

    def _sort_key(doc: Any) -> Any:
        return doc.last_discussed_at or doc.updated_at or doc.created_at

    docs_sorted = sorted(
        (d for d in docs if (d.body or "").strip()),
        key=_sort_key,
        reverse=True,
    )
    return [d.topic for d in docs_sorted[:max_topics]]


_TOPIC_NAME_RE = re.compile(r"^-\s+\[([^\]]+)\]")


def _extract_topic_name(index_line: str) -> str:
    """Pull "Redis" out of "- [Redis] strong | 8 facts | ...".
    Returns "" on parse failure."""
    m = _TOPIC_NAME_RE.match(index_line.strip())
    return m.group(1).strip() if m else ""


__all__ = [
    "SelectionDecision",
    "V3MemoryContext",
    "load_universal",
    "load_profile_only",
    "load_with_active_bodies",
]
