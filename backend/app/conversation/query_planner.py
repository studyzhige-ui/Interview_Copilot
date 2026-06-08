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
"""
from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel

from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    """Output of the unified planner."""

    # ── RAG routing ───────────────────────────────────────────────
    needs_knowledge_retrieval: bool = False
    dense_query: str = ""
    sparse_query: str = ""

    # ── Memory body selection ─────────────────────────────────────
    load_strategy: bool = False


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
    """Conservative fallback used when the planner LLM fails: no RAG, no body
    loads. The universal pass (user_profile + ability states + strategy
    one-liner) is always loaded by the engine regardless."""
    return QueryPlan(
        needs_knowledge_retrieval=False,
        dense_query="",
        sparse_query="",
        load_strategy=False,
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
        "  needs_knowledge_retrieval=false."
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

        if plan.needs_knowledge_retrieval:
            if not plan.dense_query.strip():
                plan.dense_query = user_message
            if not plan.sparse_query.strip():
                plan.sparse_query = _keyword_query(user_message)
        else:
            plan.dense_query = ""
            plan.sparse_query = ""

        # Recall-off contract guard.
        if not global_memory_on:
            plan.load_strategy = False
        return plan
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query planner failed, using conservative fallback: %s", exc)
        return fallback_query_plan(user_message)


__all__ = [
    "QueryPlan",
    "fallback_query_plan",
    "plan_query",
]
