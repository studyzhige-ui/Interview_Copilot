"""One-call conversation planner with a single RAG intent contract."""

from __future__ import annotations

import json
import logging
import re
import asyncio

from pydantic import BaseModel, Field, model_validator

from app.core.llm_client_factory import get_internal_llm
from app.core.context_budget import RequestBudget
from app.core.internal_models import get_internal_model_profile
from app.core.tokens import token_count
from app.core.execution_errors import ModelOutcomeUnknownError
from app.usage.service import ModelBudgetExceededError
from app.prompts.chat import build_query_planner_system_prompt
from app.rag.domain.models import SearchIntent
from app.rag.policy import current_rag_policy
from app.conversation.application.source_requests import ReadOnlySourceRequest
from app.conversation.application.source_requests import fallback_source_requests
from app.conversation.application.source_requests import strip_planner_identities

logger = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    needs_knowledge_retrieval: bool = False
    intents: list[SearchIntent] = Field(default_factory=list)
    source_requests: list[ReadOnlySourceRequest] = Field(
        default_factory=list,
        max_length=4,
    )
    referenced_question_indexes: list[int] = Field(default_factory=list)
    planner_failed: bool = False

    @model_validator(mode="after")
    def one_bounded_request_per_owner(self) -> "QueryPlan":
        selected: list[ReadOnlySourceRequest] = []
        seen: set[str] = set()
        for request in self.source_requests:
            if request.kind in seen:
                continue
            seen.add(request.kind)
            selected.append(request)
        self.source_requests = selected
        return self


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
        source_requests=fallback_source_requests(user_message),
        planner_failed=True,
    )


async def plan_query(
    *,
    user_message: str,
    recent_turns: list[dict],
    interview_questions: list[tuple[int, str]] | None = None,
    conversation_summary: str = "",
) -> QueryPlan:
    policy = current_rag_policy().retrieval
    system_prompt = build_query_planner_system_prompt(
        max_intents=policy.max_intents,
    )
    profile = await asyncio.to_thread(get_internal_model_profile, "router")
    output_limit = min(2000, profile.max_output_tokens)
    input_limit = min(
        16000, RequestBudget.resolve(profile.context_window, output_limit).input_limit
    )
    selected_turns = list(recent_turns)
    selected_questions = list(interview_questions or [])

    def render() -> str:
        parts = [system_prompt]
        if conversation_summary:
            parts.append(
                "[Context Summary: lossy historical reference, not current facts]\n"
                + conversation_summary
            )
        if selected_questions:
            parts.append(
                "[Interview Questions]\n"
                + "\n".join(f"Q{i}: {q}" for i, q in selected_questions)
            )
        parts.append("[Recent Turns]\n" + _format_recent_turns(selected_turns))
        parts.append("[Current Query]\n" + user_message)
        return "\n\n".join(parts)

    # Routing has its own smaller model budget. Trim whole optional entries,
    # keeping the latest user input exact; this never rewrites stored history.
    while selected_turns and token_count(render()) > input_limit:
        selected_turns.pop(0)
        while selected_turns and str(selected_turns[0].get("role", "")).lower() in {
            "agent",
            "assistant",
        }:
            selected_turns.pop(0)
    while selected_questions and token_count(render()) > input_limit:
        selected_questions.pop()
    if token_count(render()) > input_limit:
        conversation_summary = ""
    if token_count(render()) > input_limit:
        return fallback_query_plan(user_message)
    available_question_indexes = {
        index for index, _question in selected_questions if index > 0
    }
    recent_text = _format_recent_turns(selected_turns)

    try:
        response = await asyncio.wait_for(
            get_internal_llm("router").acomplete(
                render(),
                response_format={"type": "json_object"},
                max_tokens=output_limit,
            ),
            timeout=20,
        )
        plan = QueryPlan(**_extract_json_payload(str(response.text)))
        # Stable owner identities are admitted typed input, never LLM output.
        # The Planner may only request a bounded source category/query.
        plan.source_requests = strip_planner_identities(plan.source_requests)
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
        plan.referenced_question_indexes = list(
            dict.fromkeys(
                index
                for index in plan.referenced_question_indexes
                if index in available_question_indexes
            )
        )
        return plan
    except (ModelBudgetExceededError, ModelOutcomeUnknownError):
        # A fallback query is not permission to continue after a quota stop or
        # unconfirmed paid dispatch/settlement. The caller retains the receipt.
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Query planner failed; using original query: %s", type(exc).__name__
        )
        return fallback_query_plan(user_message)


__all__ = [
    "QueryPlan",
    "fallback_query_plan",
    "plan_query",
]
