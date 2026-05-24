"""Unified query planner — one LLM call per chat turn.

Used by :class:`app.conversation.engine.ConversationEngine` during the
``_prepare`` phase. Replaces what used to be two separate LLM calls
(planner + selection) by giving a single fast LLM all the inputs it
needs:

  * user message + rewrite context           → query rewriting
  * knowledge_doc index + strategy/habit
    one-liner descriptions                    → which doc bodies to load
  * recall_on flag                            → privacy gate

Output (:class:`QueryPlan`):

  standalone_query / dense_query / sparse_query
      The three forms of the rewritten question — pronouns resolved,
      semantic phrasing for vector retrieval, keyword form for BM25.

  needs_knowledge_retrieval (bool)
      Whether to consult the RAG corpus this turn. (RAG no longer
      filters by source type — the BGE reranker is authoritative.)

  knowledge_topics (list[str])
      ≤ 3 knowledge_doc topic names whose full bodies should be
      loaded into the answer prompt. Must be a subset of the topic
      index injected into the prompt.

  load_strategy / load_habit (bool)
      Whether to pull the full body of strategy_doc / habit_doc.
      Their one-liner descriptions are always loaded by the universal
      pass; this flag asks for the detail.

Whether the engine needs memory body loading at all is **derived** —
``load_anything = bool(knowledge_topics) or load_strategy or
load_habit``. There's no separate ``needs_memory_retrieval`` field
because the planner now picks specifics, not just a yes/no.
"""
from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    """Output of the unified planner."""

    # ── Query rewriting ───────────────────────────────────────────
    standalone_query: str = Field(
        ..., description="Context-resolved user query (pronouns / refs out).",
    )
    dense_query: str = Field(
        ..., description="Natural-language query for vector retrieval.",
    )
    sparse_query: str = Field(
        ..., description="Keyword query for BM25 / lexical retrieval.",
    )

    # ── RAG routing ───────────────────────────────────────────────
    needs_knowledge_retrieval: bool = False

    # ── Memory body selection (absorbed selection-LLM duties) ─────
    knowledge_topics: list[str] = Field(
        default_factory=list,
        description="≤3 knowledge_doc topic names whose body to load.",
    )
    load_strategy: bool = False
    load_habit: bool = False


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


_TOPIC_NAME_RE = re.compile(r"^-\s+\[([^\]]+)\]")


def _extract_topic_names(index_lines: list[str]) -> list[str]:
    """Parse topic names out of the knowledge_doc index format
    ``- [TopicName] mastery | N facts | last-discussed — one-liner``."""
    out: list[str] = []
    for line in index_lines:
        m = _TOPIC_NAME_RE.match(line.strip())
        if m:
            out.append(m.group(1).strip())
    return out


def fallback_query_plan(user_message: str) -> QueryPlan:
    """Conservative fallback used when the planner LLM fails.

    Picks the SAFE option: do NOT trigger RAG, do NOT load any memory
    bodies. The user still gets a real answer (the universal pass —
    user_profile + descriptions — is always loaded by the engine, and
    the chat LLM can answer plenty of questions without RAG / body
    detail). This was previously "all-on" which caused token waste +
    slow turns whenever the LLM happened to hiccup.
    """
    return QueryPlan(
        standalone_query=user_message,
        dense_query=user_message,
        sparse_query=_keyword_query(user_message),
        needs_knowledge_retrieval=False,
        knowledge_topics=[],
        load_strategy=False,
        load_habit=False,
    )


async def plan_query(
    user_message: str,
    rewrite_context: str,
    *,
    knowledge_index_lines: list[str] | None = None,
    strategy_description: str = "",
    habit_description: str = "",
    recall_on: bool = True,
) -> QueryPlan:
    """One LLM call per turn: rewrite query + decide RAG + pick memory bodies.

    ``knowledge_index_lines`` / ``strategy_description`` /
    ``habit_description`` come from ``v3_context_loader.load_universal``
    — cheap DB reads the engine does just before calling the planner.

    When ``recall_on=False`` (privacy mode), the planner skips the
    memory-body fields entirely and the caller treats them all as
    False / empty.
    """
    index_lines = knowledge_index_lines or []
    valid_topics = _extract_topic_names(index_lines)

    # Compose the memory-aware portion of the prompt only when recall
    # is enabled. Privacy-mode users see neither indexes nor
    # descriptions in the prompt — the planner can still rewrite the
    # query and decide RAG.
    if recall_on:
        index_block = (
            "\n".join(index_lines) if index_lines else "(no knowledge topics yet)"
        )
        memory_section = f"""
User memory available this turn:
- Knowledge topics index (each line: ``- [TopicName] mastery | N facts | last-discussed — one-liner``):
{index_block}
- Strategy doc one-liner: {strategy_description or "(empty)"}
- Habit doc one-liner: {habit_description or "(empty)"}

Rules for memory loading:
- knowledge_topics: pick AT MOST 3 topic names from the index above (exact spelling). Pick zero when the question is unrelated to any topic.
- load_strategy: true only if the question is about answering methodology / approach the user might already have notes for.
- load_habit: true only if the question is about study cadence / practice rhythm / interview-prep emotional regulation.
- When in doubt, leave them empty — the universal layer (user_profile + descriptions) is always available.
"""
        memory_output_keys = """
  "knowledge_topics": ["<topic name from the index above>", ...],
  "load_strategy": true | false,
  "load_habit": true | false,
"""
    else:
        memory_section = (
            "Memory recall is OFF for this session — leave all memory "
            "fields empty / false."
        )
        memory_output_keys = """
  "knowledge_topics": [],
  "load_strategy": false,
  "load_habit": false,
"""

    prompt = f"""You are the query planner for a multi-turn interview copilot.
Return ONLY a JSON object matching this schema:
{{
  "standalone_query": "<context-resolved question>",
  "dense_query": "<natural-language query for semantic vector retrieval>",
  "sparse_query": "<short keyword query for BM25>",
  "needs_knowledge_retrieval": true | false,{memory_output_keys}}}

General rules:
- Resolve pronouns and follow-up references using the rewrite context.
- needs_knowledge_retrieval=true when the question is about interview
  questions / technical concepts / framework facts / official docs.
- needs_knowledge_retrieval=false for casual chat, profile updates,
  questions answerable from memory alone, or meta-questions about the
  copilot itself.

{memory_section}

Rewrite context:
{rewrite_context}

Current user message:
{user_message}
"""
    try:
        response = await agent_fast_llm.acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        payload = _extract_json_payload(str(response.text))
        plan = QueryPlan(**payload)
        # Defensive backfills.
        if not plan.dense_query.strip():
            plan.dense_query = plan.standalone_query
        if not plan.sparse_query.strip():
            plan.sparse_query = _keyword_query(plan.standalone_query)
        # Topic names: hard-filter against the injected index so the
        # LLM can't invent a name and downstream loads silently miss.
        if plan.knowledge_topics:
            allowed = set(valid_topics)
            plan.knowledge_topics = [
                t for t in plan.knowledge_topics if t in allowed
            ][:3]
        # Recall-off contract guard: even if the LLM ignored the
        # instruction, drop any memory loads.
        if not recall_on:
            plan.knowledge_topics = []
            plan.load_strategy = False
            plan.load_habit = False
        return plan
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query planner failed, using conservative fallback: %s", exc)
        return fallback_query_plan(user_message)


__all__ = [
    "QueryPlan",
    "fallback_query_plan",
    "plan_query",
]
