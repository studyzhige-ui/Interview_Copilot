import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)

KnowledgeSource = Literal["interview_qa", "official_docs"]
MemoryType = Literal[
    "user_profile",
    "interaction_preference",
    "feedback_rule",
    "project_reference",
]
AnswerMode = Literal[
    "direct_chat",
    "knowledge_qa",
    "interview_learning",
    "review",
    "preference_update",
]


class QueryPlan(BaseModel):
    standalone_query: str = Field(..., description="Context-resolved user query.")
    dense_query: str = Field(..., description="Natural-language query for vector retrieval.")
    sparse_query: str = Field(..., description="Keyword query for lexical/BM25 retrieval.")
    needs_memory_retrieval: bool = False
    memory_types: list[MemoryType] = Field(default_factory=list)
    needs_knowledge_retrieval: bool = False
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list)
    answer_mode: AnswerMode = "direct_chat"
    reasoning: str = ""


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
    terms = re.findall(r"[a-zA-Z0-9_+#.-]+|[\u4e00-\u9fff]{2,}", text)
    return " ".join(dict.fromkeys(terms[:12]))


def fallback_query_plan(user_message: str) -> QueryPlan:
    return QueryPlan(
        standalone_query=user_message,
        dense_query=user_message,
        sparse_query=_keyword_query(user_message),
        needs_memory_retrieval=True,
        memory_types=[
            "user_profile",
            "interaction_preference",
            "feedback_rule",
            "project_reference",
        ],
        needs_knowledge_retrieval=True,
        knowledge_sources=["interview_qa"],
        answer_mode="knowledge_qa",
        reasoning="Fallback plan after planner failure.",
    )


async def plan_query(user_message: str, rewrite_context: str) -> QueryPlan:
    prompt = f"""
You are the query planner for a multi-turn interview copilot.
Return only a JSON object matching this schema:
{{
  "standalone_query": "context-resolved user question",
  "dense_query": "natural-language query for semantic vector retrieval",
  "sparse_query": "short keyword query for BM25/lexical retrieval",
  "needs_memory_retrieval": true,
  "memory_types": ["user_profile", "interaction_preference", "feedback_rule", "project_reference"],
  "needs_knowledge_retrieval": true,
  "knowledge_sources": ["interview_qa", "official_docs"],
  "answer_mode": "direct_chat | knowledge_qa | interview_learning | review | preference_update",
  "reasoning": "short audit note"
}}

Rules:
- Resolve pronouns and follow-up references using the context.
- Use memory for user preferences, prior project references, feedback rules, or durable profile facts.
- Use knowledge retrieval for interview questions, official docs, technical concepts, or code/framework facts.
- Do not use "personal_memory" as a knowledge source.
- For casual chat, set needs_knowledge_retrieval=false and answer_mode=direct_chat.
- For explicit preference changes, set answer_mode=preference_update.
- For interview retrospectives, weak-point review, or learning plans, set answer_mode=review or interview_learning.

Context:
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
        if not plan.dense_query.strip():
            plan.dense_query = plan.standalone_query
        if not plan.sparse_query.strip():
            plan.sparse_query = _keyword_query(plan.standalone_query)
        return plan
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query planner failed, using fallback: %s", exc)
        return fallback_query_plan(user_message)
