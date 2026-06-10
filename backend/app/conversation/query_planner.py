"""Unified query planner — one LLM call per chat turn.

Used by :class:`app.conversation.engine.ConversationEngine` during the
``_prepare`` phase. One fast-LLM call decides:

  * session state + recent turns                → pronoun resolution
  * learning_strategy one-liner                 → whether to load its full body
  * global_memory_on flag                       → privacy gate
  * current user message                        → the question to plan around

Prompt assembly follows "large models attend more to the end of the context":
system prompt → available memory files → session state → recent turns → current
user message (last).

Output (:class:`QueryPlan`):

  needs_knowledge_retrieval (bool)
      Whether to consult the RAG corpus this turn.

  dense_query / sparse_query (str)
      Rewritten queries for vector retrieval / BM25. Defaults to the original
      user message when the LLM omits them and RAG is on.

  load_strategy (bool)
      Whether to pull the full learning_strategy doc body. Its one-liner is
      always loaded by the universal pass; this asks for the detail. (The
      user_profile body and the active ability states are always loaded by the
      universal pass — they're cheap — so the planner makes no decision about
      them.)

  planner_failed (bool)
      Runtime flag set ONLY by the failure fallback (planner crashed →
      original-question retrieval). Never part of the LLM's JSON schema.
"""
from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel

from app.core.config import settings
from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)


class SubQuery(BaseModel):
    """One leg of a multi-intent question (retrieval plan §2.1). A flat list —
    no nesting. dense for vector retrieval, sparse for BM25."""

    dense_query: str = ""
    sparse_query: str = ""


class QueryPlan(BaseModel):
    """Output of the unified planner."""

    # ── RAG routing ───────────────────────────────────────────────
    needs_knowledge_retrieval: bool = False
    dense_query: str = ""
    sparse_query: str = ""
    # Only for clearly multi-intent questions ("explain A and B, compare C").
    # Empty for normal single questions. Capped at MAX_SUB_QUERIES.
    sub_queries: list[SubQuery] = []

    # ── Memory body selection ─────────────────────────────────────
    load_strategy: bool = False

    # ── Runtime flags (NEVER part of the LLM's output schema) ─────
    # Set by the failure fallback only — an LLM-emitted value would be
    # noise (retrieval plan §2.1). The engine forwards it into the
    # turn's RetrievalState.
    planner_failed: bool = False


def _extract_json_payload(raw_text: str) -> dict:
    raw_text = str(raw_text or "").strip()
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(1))
    return payload if isinstance(payload, dict) else {}


def _keyword_query(text: str) -> str:
    """ASCII + CJK terms, deduped, up to 12 — feeds BM25 fallback."""
    terms = re.findall(r"[a-zA-Z0-9_+#.-]+|[一-鿿]{2,}", text)
    return " ".join(dict.fromkeys(terms[:12]))


def _format_recent_turns(recent_turns: list[dict]) -> str:
    """Render ``[{role, content, ...}]`` as ``User: ...\\nAgent: ...``."""
    if not recent_turns:
        return "(no prior turns)"
    return "\n".join(
        f"{m.get('role', '?')}: {m.get('content', '')}" for m in recent_turns
    )


def fallback_query_plan(user_message: str) -> QueryPlan:
    """Fallback when the planner LLM fails: retrieve with the ORIGINAL
    question instead of giving up (retrieval plan §2.1) — the candidates
    still pass the reranker + threshold, so a useless retrieval costs
    latency, while skipping it loses answers. Memory body loads stay off
    (can't be decided without the planner).

    ``planner_failed=True`` is stamped so the engine can mark the turn's
    retrieval state and fallback_rate stays observable — a persistently
    failing planner makes EVERY message (incl. casual chat) pay an
    embedding + Milvus + rerank round-trip, which must show up in trace,
    never silently.
    """
    return QueryPlan(
        needs_knowledge_retrieval=True,
        dense_query=user_message,
        sparse_query=_keyword_query(user_message),
        load_strategy=False,
        planner_failed=True,
    )


async def plan_query(
    *,
    user_message: str,
    recent_turns: list[dict],
    learning_strategy_description: str = "",
    global_memory_on: bool = True,
) -> QueryPlan:
    """One LLM call per turn: rewrite query for RAG + decide whether to load the
    full learning_strategy body.

    ``learning_strategy_description`` comes from
    ``v3_context_loader.load_universal``. When ``global_memory_on=False``
    (privacy mode) the memory section is omitted and any memory load is forced
    off.
    """
    if global_memory_on:
        memory_files_slot = (
            "[Available Memory Files]\n"
            f"Learning-strategy doc one-liner: {learning_strategy_description or '(empty)'}\n"
            "\n"
            "Memory load rules:\n"
            "- load_strategy: true only if the question is about answering methodology / "
            "review approach / training the user might have strategy notes for. When in doubt, "
            "leave it false — the user_profile and ability states are always available."
        )
        memory_output_keys = '  "load_strategy": true | false,\n'
    else:
        memory_files_slot = ""   # privacy mode: omit the whole slot
        memory_output_keys = '  "load_strategy": false,\n'

    system_prompt = (
        "You are the query planner for an interview copilot. Decide what "
        "context this turn needs.\n"
        "\n"
        "Return ONLY a JSON object matching this schema:\n"
        "{\n"
        '  "needs_knowledge_retrieval": true | false,\n'
        '  "dense_query": "<natural-language query for semantic vector retrieval>",\n'
        '  "sparse_query": "<short keyword query for BM25>",\n'
        '  "sub_queries": [{"dense_query": "...", "sparse_query": "..."}],\n'
        f"{memory_output_keys}"
        "}\n"
        "\n"
        "Rules:\n"
        "- needs_knowledge_retrieval=true when the question is about interview\n"
        "  questions / technical concepts / framework facts / official docs.\n"
        "- needs_knowledge_retrieval=false for casual chat, profile updates,\n"
        "  questions answerable from memory alone, or meta-questions about\n"
        "  the copilot itself.\n"
        "- When generating dense_query / sparse_query, resolve any pronouns or\n"
        "  follow-up references using [Recent Turns]. Leave both empty when\n"
        "  needs_knowledge_retrieval=false.\n"
        "- sub_queries: ONLY when the question has multiple distinct intents\n"
        "  (e.g. 'explain A and B, then compare C'). Emit one entry per\n"
        "  independent intent; keep dense_query/sparse_query as the overall\n"
        "  question. For a normal single question, return an empty list — do\n"
        "  NOT split a single complex question or a follow-up."
    )

    parts: list[str] = [system_prompt]
    if memory_files_slot:
        parts.append(memory_files_slot)
    parts.append(f"[Recent Turns]\n{_format_recent_turns(recent_turns)}")
    # The actual user message appears EXACTLY ONCE, last.
    parts.append(f"[Current Query]\n{user_message}")

    prompt = "\n\n".join(parts)

    try:
        response = await agent_fast_llm.acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        payload = _extract_json_payload(str(response.text))
        plan = QueryPlan(**payload)
        # planner_failed is a runtime flag owned by the failure fallback — a
        # successful parse must never let the model set it.
        plan.planner_failed = False

        if plan.needs_knowledge_retrieval:
            if not plan.dense_query.strip():
                plan.dense_query = user_message
            if not plan.sparse_query.strip():
                plan.sparse_query = _keyword_query(user_message)
            # Drop empty sub-queries and enforce the defensive hard cap
            # (the engine/retriever cap too, but keep the plan itself clean).
            valid_subs = [
                sq for sq in plan.sub_queries
                if sq.dense_query.strip() or sq.sparse_query.strip()
            ]
            plan.sub_queries = valid_subs[:settings.MAX_SUB_QUERIES]
        else:
            plan.dense_query = ""
            plan.sparse_query = ""
            plan.sub_queries = []

        # Recall-off contract guard.
        if not global_memory_on:
            plan.load_strategy = False
        return plan
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Query planner failed, falling back to original-question "
            "retrieval (planner_failed=True): %s", exc,
        )
        return fallback_query_plan(user_message)


__all__ = [
    "QueryPlan",
    "SubQuery",
    "fallback_query_plan",
    "plan_query",
]
