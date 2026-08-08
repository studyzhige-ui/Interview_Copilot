"""One-call conversation planner with a single RAG intent contract."""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from app.core.llm_client_factory import get_internal_llm
from app.prompts.chat import build_query_planner_system_prompt
from app.rag.contracts import SearchIntent
from app.rag.policy import current_rag_policy

logger = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    needs_knowledge_retrieval: bool = False
    intents: list[SearchIntent] = Field(default_factory=list)
    load_strategy: bool = False
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


def _keyword_terms(text: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9_+#.-]+|[一-鿿]{2,}", text)
    return list(dict.fromkeys(terms[:12]))


def _format_recent_turns(recent_turns: list[dict]) -> str:
    if not recent_turns:
        return "(no prior turns)"
    return "\n".join(
        f"{message.get('role', '?')}: {message.get('content', '')}"
        for message in recent_turns
    )


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]", "", value.casefold())


def _validated_required_terms(intent: SearchIntent, source_text: str) -> list[str]:
    source = _compact(source_text)
    return [term for term in intent.required_terms if _compact(term) in source]


def fallback_query_plan(user_message: str) -> QueryPlan:
    return QueryPlan(
        needs_knowledge_retrieval=True,
        intents=[
            SearchIntent(
                query=user_message,
                keywords=_keyword_terms(user_message),
            )
        ],
        planner_failed=True,
    )


async def plan_query(
    *,
    user_message: str,
    recent_turns: list[dict],
    learning_strategy_description: str = "",
    global_memory_on: bool = True,
) -> QueryPlan:
    memory_slot = (
        "[Available Memory Files]\nLearning-strategy description: "
        f"{learning_strategy_description or '(empty)'}"
        if global_memory_on
        else ""
    )
    policy = current_rag_policy().retrieval
    system_prompt = build_query_planner_system_prompt(
        global_memory_on=global_memory_on,
        max_intents=policy.max_intents,
    )
    parts = [system_prompt]
    if memory_slot:
        parts.append(memory_slot)
    recent_text = _format_recent_turns(recent_turns)
    parts.append(f"[Recent Turns]\n{recent_text}")
    parts.append(f"[Current Query]\n{user_message}")

    try:
        response = await get_internal_llm("router").acomplete(
            "\n\n".join(parts),
            response_format={"type": "json_object"},
        )
        plan = QueryPlan(**_extract_json_payload(str(response.text)))
        plan.planner_failed = False
        if plan.needs_knowledge_retrieval:
            source_text = f"{recent_text}\n{user_message}"
            intents: list[SearchIntent] = []
            for intent in plan.intents:
                if not intent.query:
                    continue
                if intent.alternate_query == intent.query:
                    intent.alternate_query = ""
                if not intent.keywords:
                    intent.keywords = _keyword_terms(intent.query)
                intent.required_terms = _validated_required_terms(intent, source_text)
                intents.append(intent)
            plan.intents = intents[: policy.max_intents]
            if not plan.intents:
                plan.intents = fallback_query_plan(user_message).intents
        else:
            plan.intents = []
        if not global_memory_on:
            plan.load_strategy = False
        return plan
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query planner failed; using original query: %s", exc)
        return fallback_query_plan(user_message)


__all__ = [
    "QueryPlan",
    "fallback_query_plan",
    "plan_query",
]
