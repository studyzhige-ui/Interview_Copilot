"""Unified query planner — one LLM call per chat turn.

Used by :class:`app.conversation.engine.ConversationEngine` during the
``_prepare`` phase. Replaces what used to be two separate LLM calls
(planner + selection) by giving a single fast LLM all the inputs it
needs:

  * session state + recent turns                → pronoun resolution
  * knowledge_doc index + strategy/habit
    one-liner descriptions                       → which doc bodies to load
  * global_memory_on flag                               → privacy gate
  * current user message                         → the question to plan around

Prompt assembly follows the "large models attend more to the end of
the context" rule: system prompt → available memory files → session
state → recent turns → current user message (last). This is the same
slot order the answer pipeline uses.

Output (:class:`QueryPlan`):

  needs_knowledge_retrieval (bool)
      Whether to consult the RAG corpus this turn.

  dense_query / sparse_query (str)
      Rewritten queries for vector retrieval / BM25. Only meaningful
      when ``needs_knowledge_retrieval=True``; defaults to the
      original user message when the LLM omits them.

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
load_habit``. There's no separate ``needs_memory_retrieval`` field.

No ``standalone_query`` field — the answer LLM resolves pronouns
itself using ``[Recent Turns]``. We don't bake a second rewrite into
the planner's output schema since (a) it added 5+ tokens to every
output for no downstream consumer that strictly needed it, (b) the
planner still does the pronoun work internally to produce
``dense_query`` / ``sparse_query`` for RAG.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    """Output of the unified planner."""

    # ── RAG routing ───────────────────────────────────────────────
    needs_knowledge_retrieval: bool = False
    # Only meaningful when needs_knowledge_retrieval=True; otherwise
    # the engine ignores them (and the LLM is instructed to leave
    # them empty).
    dense_query: str = ""
    sparse_query: str = ""

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


def _format_recent_turns(recent_turns: list[dict]) -> str:
    """Render ``[{role, content, ...}]`` as ``User: ...\\nAgent: ...``."""
    if not recent_turns:
        return "(no prior turns)"
    return "\n".join(
        f"{m.get('role', '?')}: {m.get('content', '')}" for m in recent_turns
    )


def _format_session_state(session_state: dict) -> str:
    if not session_state:
        return "(empty)"
    return json.dumps(session_state, ensure_ascii=False, indent=2)


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
        needs_knowledge_retrieval=False,
        dense_query="",
        sparse_query="",
        knowledge_topics=[],
        load_strategy=False,
        load_habit=False,
    )


async def plan_query(
    *,
    user_message: str,
    session_state: dict,
    recent_turns: list[dict],
    knowledge_index_lines: list[str] | None = None,
    strategy_description: str = "",
    habit_description: str = "",
    global_memory_on: bool = True,
) -> QueryPlan:
    """One LLM call per turn: rewrite query for RAG + decide memory bodies.

    All inputs are structured (not pre-rendered strings) so the planner
    builds its own prompt with the slot order we want — and the user
    message appears EXACTLY ONCE, at the very end, where the LLM's
    attention is highest.

    ``session_state`` / ``recent_turns`` come from
    ``transcript_service`` (engine reads them directly).
    ``knowledge_index_lines`` / ``strategy_description`` /
    ``habit_description`` come from ``v3_context_loader.load_universal``.

    When ``global_memory_on=False`` (privacy mode), the memory section is
    omitted entirely and the contract enforces empty memory output.
    """
    index_lines = knowledge_index_lines or []
    valid_topics = _extract_topic_names(index_lines)

    # ── Slot bodies (built lazily so privacy mode skips memory) ──

    if global_memory_on:
        index_block = (
            "\n".join(index_lines) if index_lines else "(no knowledge topics yet)"
        )
        memory_files_slot = (
            "[Available Memory Files]\n"
            f"Knowledge topics index "
            f"(each line: ``- [TopicName] mastery | N facts | last-discussed — one-liner``):\n"
            f"{index_block}\n"
            f"Strategy doc one-liner: {strategy_description or '(empty)'}\n"
            f"Habit doc one-liner:    {habit_description or '(empty)'}\n"
            "\n"
            "Memory load rules:\n"
            "- knowledge_topics: pick AT MOST 3 topic names from the index above (exact spelling). "
            "Empty when the question is unrelated to any topic.\n"
            "- load_strategy: true only if the question is about answering methodology / approach "
            "the user might have notes for.\n"
            "- load_habit: true only if the question is about study cadence / practice rhythm / "
            "interview-prep emotional regulation.\n"
            "- When in doubt, leave them empty — the universal layer (user_profile + descriptions) "
            "is always available."
        )
        memory_output_keys = (
            '  "knowledge_topics": ["<topic name from the index above>", ...],\n'
            '  "load_strategy": true | false,\n'
            '  "load_habit": true | false,\n'
        )
    else:
        memory_files_slot = ""   # privacy mode: omit the whole slot
        memory_output_keys = (
            '  "knowledge_topics": [],\n'
            '  "load_strategy": false,\n'
            '  "load_habit": false,\n'
        )

    # ── System prompt + output schema + general rules ───────────

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
        "  follow-up references using [Session State] + [Recent Turns]. Leave\n"
        "  both empty when needs_knowledge_retrieval=false."
    )

    # ── Assemble in slot order (LLM attends more to the END) ────

    parts: list[str] = [system_prompt]
    if memory_files_slot:
        parts.append(memory_files_slot)
    parts.append(f"[Session State]\n{_format_session_state(session_state)}")
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

        # Defensive backfills — only meaningful when RAG is on.
        if plan.needs_knowledge_retrieval:
            if not plan.dense_query.strip():
                plan.dense_query = user_message
            if not plan.sparse_query.strip():
                plan.sparse_query = _keyword_query(user_message)
        else:
            # Drop any noise the LLM might have generated.
            plan.dense_query = ""
            plan.sparse_query = ""

        # Topic names: hard-filter against the injected index so the
        # LLM can't invent a name and downstream loads silently miss.
        if plan.knowledge_topics:
            allowed = set(valid_topics)
            plan.knowledge_topics = [
                t for t in plan.knowledge_topics if t in allowed
            ][:3]
        # Recall-off contract guard: even if the LLM ignored the
        # instruction, drop any memory loads.
        if not global_memory_on:
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
