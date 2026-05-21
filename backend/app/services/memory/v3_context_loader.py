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
# Hard upper bound on how long we wait for the topic-selection LLM. Beyond
# this the chat turn proceeds on the deterministic last_discussed_at
# fallback. Should be << total chat-turn latency budget.
SELECTION_LLM_TIMEOUT_SEC = 2.5

# Cache window for selection results. The most common pattern is the user
# asking a follow-up that picks the same topics; caching for a minute
# avoids paying the selection LLM cost on every keystroke-driven turn.
_SELECTION_CACHE_TTL_SEC = 60.0
_SELECTION_CACHE: dict[tuple[str, str, int], tuple[float, list[str]]] = {}
_SELECTION_CACHE_MAX_ENTRIES = 512


@dataclass
class V3MemoryContext:
    """Bundle of memory artifacts to inject into a chat turn's prompt."""

    user_profile_body: str = ""
    knowledge_index_lines: list[str] = field(default_factory=list)
    strategy_body: str = ""
    habit_body: str = ""
    # Bodies of topics actively pulled in for this query.
    # Maps topic_name -> body markdown.
    active_knowledge_bodies: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """Render the whole bundle as a single markdown string suitable
        for injection into a system prompt section."""
        parts: list[str] = []

        if self.user_profile_body.strip():
            parts.append("# 用户画像\n" + self.user_profile_body.strip())

        if self.knowledge_index_lines:
            parts.append("# 知识主题索引")
            parts.append("\n".join(self.knowledge_index_lines))

        if self.active_knowledge_bodies:
            parts.append("# 本次对话相关的主题详情")
            for topic, body in self.active_knowledge_bodies.items():
                parts.append(f"## {topic}\n{body.strip()}")

        if self.strategy_body.strip():
            parts.append("# 答题策略\n" + self.strategy_body.strip())

        if self.habit_body.strip():
            parts.append("# 学习习惯与心态\n" + self.habit_body.strip())

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
    """Cheap pass — load user_profile (full) + all three index/single
    bodies. No LLM call.

    Always called regardless of session type — these artifacts are
    universal personalisation context (the user is the user even when
    they're chatting about non-interview topics).
    """
    return V3MemoryContext(
        user_profile_body=user_profile_doc_service.load(user_id),
        knowledge_index_lines=knowledge_doc_service.list_index_lines(
            user_id, max_topics=50,
        ),
        strategy_body=strategy_doc_service.load(user_id),
        habit_body=habit_doc_service.load(user_id),
    )


async def load_with_active_bodies(
    user_id: str,
    *,
    query: str,
    max_active_topics: int = 3,
) -> V3MemoryContext:
    """Universal pass + on-demand knowledge_doc bodies for topics the
    LLM picks as relevant.

    Returns a context with ``active_knowledge_bodies`` populated when
    the selection LLM found relevant topics OR the deterministic
    fallback (most-recently-discussed) returned candidates. Empty
    only when there are no indexed topics or the LLM and fallback
    both yield nothing — never silently drops bodies just because the
    selection LLM had a bad day.
    """
    ctx = load_universal(user_id)

    if not ctx.knowledge_index_lines or not (query or "").strip():
        return ctx

    selected = await _select_active_topics(
        user_id=user_id,
        query=query,
        index_lines=ctx.knowledge_index_lines,
        max_topics=max_active_topics,
    )
    if not selected:
        return ctx

    bodies: dict[str, str] = {}
    for topic in selected:
        doc = knowledge_doc_service.load(user_id, topic)
        if doc and (doc.body or "").strip():
            bodies[topic] = doc.body
    ctx.active_knowledge_bodies = bodies
    return ctx


# ──────────────────────────────────────────────────────────────────────
# Selection LLM
# ──────────────────────────────────────────────────────────────────────


async def _select_active_topics(
    *,
    user_id: str,
    query: str,
    index_lines: list[str],
    max_topics: int,
) -> list[str]:
    """Ask the fast LLM which topics are relevant; on any failure or
    timeout, fall back to the most-recently-discussed topics.

    Hardening (Checkpoint 3, F3+F8):

    * **Cache** results per ``(user_id, lowercased query, max_topics)``
      for 60s — a follow-up question typically wants the same topics
      and the LLM round-trip can be skipped entirely.
    * **Timeout** the LLM call at ``SELECTION_LLM_TIMEOUT_SEC`` so the
      chat turn never blocks on a slow vendor.
    * **Fallback** to a deterministic "top-N by last_discussed_at"
      heuristic on any LLM failure (timeout, malformed JSON, vendor
      error). Silent zero-body is a quality regression; non-zero
      stale-but-related body is at least personalised.
    * **Metric** ``memory.selection_llm_failed`` emitted per failure
      with a ``reason`` label so ops can alarm on it.
    """
    if not index_lines:
        return []

    cache_key = (user_id, query.strip().lower(), max_topics)
    now = time.monotonic()
    cached = _SELECTION_CACHE.get(cache_key)
    if cached is not None:
        expiry, topics = cached
        if expiry > now:
            return list(topics)
        # Stale — drop it now so the cache doesn't grow unboundedly with
        # expired keys.
        _SELECTION_CACHE.pop(cache_key, None)

    indexed_names = {_extract_topic_name(line) for line in index_lines}
    indexed_names.discard("")

    fallback_reason: str | None = None

    prompt = CONTEXT_SELECTION_PROMPT.format(
        knowledge_index="\n".join(index_lines),
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
        topics = parsed.get("selected_topics") or []
        if not isinstance(topics, list):
            raise ValueError("selected_topics was not a list")
        out = [t for t in topics if isinstance(t, str) and t in indexed_names][:max_topics]
        _cache_selection(cache_key, out)
        return out
    except asyncio.TimeoutError:
        fallback_reason = "timeout"
        logger.warning(
            "v3_context_loader: selection LLM timed out after %.2fs; "
            "falling back to last_discussed_at heuristic",
            SELECTION_LLM_TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001
        fallback_reason = type(exc).__name__
        logger.warning(
            "v3_context_loader: selection LLM failed (%s); "
            "falling back to last_discussed_at heuristic",
            exc,
        )

    _metric_incr(
        "memory.selection_llm_failed",
        user_id=user_id,
        reason=fallback_reason,
    )

    # Deterministic fallback: pick the N most-recently-discussed topics
    # that actually have a body. Doesn't need the LLM and is safe under
    # any failure mode (DB down → empty list → empty bodies, same as
    # the old behaviour). Prefer this over zero-body so chat quality
    # degrades gracefully.
    fallback = _fallback_recent_topics(user_id, max_topics=max_topics)
    fallback = [t for t in fallback if t in indexed_names]
    _cache_selection(cache_key, fallback)
    return fallback


def _cache_selection(key: tuple[str, str, int], topics: list[str]) -> None:
    """Insert a cache entry. Cheap LRU-by-insertion-order eviction
    keeps the dict bounded; we don't care about strict LRU semantics
    since entries TTL out in 60s anyway."""
    if len(_SELECTION_CACHE) >= _SELECTION_CACHE_MAX_ENTRIES:
        # Drop the oldest insertion-order key.
        try:
            oldest = next(iter(_SELECTION_CACHE))
            _SELECTION_CACHE.pop(oldest, None)
        except StopIteration:
            pass
    _SELECTION_CACHE[key] = (time.monotonic() + _SELECTION_CACHE_TTL_SEC, list(topics))


def _fallback_recent_topics(user_id: str, *, max_topics: int) -> list[str]:
    """Top-N knowledge_doc topics by ``last_discussed_at`` DESC. Used
    when the selection LLM fails — better than returning zero bodies."""
    try:
        docs = knowledge_doc_service.load_all(user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("v3_context_loader: fallback recent topics failed: %s", exc)
        return []

    def _sort_key(doc: Any) -> Any:
        # Sort recent-first; rows with no last_discussed_at fall to the
        # bottom (they're stale).
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
    "V3MemoryContext",
    "load_universal",
    "load_profile_only",
    "load_with_active_bodies",
]
