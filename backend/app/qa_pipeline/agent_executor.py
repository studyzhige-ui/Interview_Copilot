"""L1 QA orchestrator — ``stream_chat_with_agent``.

Drives a single chat turn through plan → retrieve → answer → persist,
with telemetry and post-turn maintenance running in the background.
"""

import asyncio
import logging
import time
import traceback
from typing import AsyncGenerator

import openai
import tiktoken
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler

from app.core.background_tasks import safe_background_task
from app.qa_pipeline.planner import plan_query
from app.rag.embeddings import agent_fast_llm
from app.rag.knowledge_retriever import knowledge_retriever
from app.services.chat.chat_history_service import transcript_service
from app.services.chat.context_assembly_pipeline import context_pipeline, prompt_renderer
from app.services.memory.post_turn_maintenance import post_turn_maintenance_service
from app.services.memory.retrieval_service import memory_retrieval_service
from app.services.telemetry_service import log_interaction_metrics

logger = logging.getLogger(__name__)

token_counter = TokenCountingHandler(
    tokenizer=tiktoken.get_encoding("cl100k_base").encode,
)
Settings.callback_manager = CallbackManager([token_counter])

DIRECT_SYSTEM_RULES = """You are Interview Copilot, a concise technical interview assistant.
Use the provided session state and memories only when relevant. If context is insufficient, say what is missing."""

RAG_SYSTEM_RULES = """You are Interview Copilot, a concise technical interview assistant.
Use retrieved knowledge as evidence and avoid inventing sources."""


def _humanize_exc(exc: Exception) -> str:
    """Translate an upstream exception into a Chinese sentence the user
    sees in the chat bubble.

    Don't leak provider error codes (e.g. "401 Invalid API Key") into
    the UI — that's a developer detail. Tell the user what to *do*.

    Common cases:
      * ``openai.AuthenticationError`` (HTTP 401) — wrong / revoked /
        empty API key. Almost always: the user-saved key in
        ``user_api_keys`` for the active provider expired, or .env
        ``*_API_KEY`` was empty.
      * ``openai.RateLimitError`` (HTTP 429) — vendor throttled us.
      * ``openai.APIConnectionError`` — DNS / network / vendor down.
      * ``openai.APITimeoutError`` — request timed out.
      * ``openai.BadRequestError`` (HTTP 400) — prompt too long / bad
        params; we expose the vendor's short reason since it's
        actionable (e.g. "max_tokens exceeded").
      * everything else — generic "system error, please retry".

    Full exception still goes to backend log via the existing
    logger.error() at the call site for ops to inspect.
    """
    if isinstance(exc, openai.AuthenticationError):
        return (
            "当前模型的密钥无效或已失效。请到「模型」页面，找到对应厂商卡片，"
            "重新配置 API 密钥后再试。"
        )
    if isinstance(exc, openai.RateLimitError):
        return "模型厂商当前限流（请求过于频繁），请稍等几秒后重试。"
    if isinstance(exc, openai.APIConnectionError):
        return "无法连接到模型服务，请检查网络或稍后再试。"
    if isinstance(exc, openai.APITimeoutError):
        return "模型响应超时，请重试一次。"
    if isinstance(exc, openai.BadRequestError):
        # BadRequest body often has actionable text (token limit, etc.).
        try:
            detail = (exc.body or {}).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            detail = ""
        if detail:
            return f"请求被模型拒绝：{detail}"
        return "请求被模型拒绝（可能是上下文过长或参数不合规）。"
    return "系统出了点问题，请稍后再试。如果反复发生，请把这次操作的时间告诉运维。"


async def stream_chat_with_agent(
    user_message: str,
    user_id: str,
    session_id: str = "default_session",
) -> AsyncGenerator[str, None]:
    start_time = time.time()
    token_counter.reset_counts()
    retrieval_attempted = False
    retrieval_hit = False

    try:
        yield "[status] 正在准备对话上下文...\n"
        transcript_service.ensure_session(session_id, user_id)

        yield "[status] 正在分析问题并规划上下文...\n"
        rewrite_context = context_pipeline.assemble_rewrite_context(
            session_id=session_id,
            current_query=user_message,
        )
        query_plan = await plan_query(
            user_message=user_message,
            rewrite_context=rewrite_context.context_text,
        )
        standalone_query = query_plan.standalone_query

        yield "[status] 正在并发召回记忆和知识库...\n"
        # user_profile: always loaded directly from DB (like hermes USER.md).
        # This is "who you are" data (name, role, target companies, …)
        # — small and always relevant, so it bypasses the recall toggle.
        user_profile = memory_retrieval_service.load_user_profile(user_id)

        # interview_fact recall is OPT-IN. Honour the session-local toggle
        # first (set by the chat-header switch), falling back to the
        # user's account-wide default (个人中心). This is what users mean
        # when they ask "don't pull old answers into this conversation":
        # we still keep user_profile in scope, but we skip the vector
        # search over past Q&A snippets entirely. Saves a Milvus round-trip
        # and avoids contaminating the LLM with stale facts.
        from app.services.memory.recall_policy import recall_enabled_for_session
        recall_on = recall_enabled_for_session(session_id, user_id)
        memory_task = asyncio.create_task(
            memory_retrieval_service.recall_relevant(
                user_id=user_id,
                query=query_plan.dense_query or standalone_query,
                memory_types=["interview_fact"],
            )
        ) if (query_plan.needs_memory_retrieval and recall_on) else None
        knowledge_task = asyncio.create_task(
            knowledge_retriever.retrieve(
                dense_query=query_plan.dense_query or standalone_query,
                sparse_query=query_plan.sparse_query,
                source_types=query_plan.knowledge_sources,
                user_id=user_id,
            )
        ) if query_plan.needs_knowledge_retrieval else None

        relevant_memories = await memory_task if memory_task else []
        knowledge_result = await knowledge_task if knowledge_task else None
        retrieval_attempted = bool(knowledge_task)
        retrieval_hit = bool(knowledge_result and knowledge_result.retrieval_hit)

        yield "[status] 正在生成回答...\n\n"
        answer_context = context_pipeline.assemble_answer_context(
            session_id=session_id,
            current_query=standalone_query,
            user_profile=user_profile,
            relevant_memories=relevant_memories,
            knowledge_chunks=knowledge_result.chunks if knowledge_result else [],
        )

        if not query_plan.needs_knowledge_retrieval:
            prompt = prompt_renderer.render_answer_prompt(
                answer_context,
                system_rules=DIRECT_SYSTEM_RULES,
            )
            response_generator = await agent_fast_llm.astream_complete(prompt)
        else:
            prompt = prompt_renderer.render_answer_prompt(
                answer_context,
                system_rules=RAG_SYSTEM_RULES,
            )
            response_generator = await Settings.llm.astream_complete(prompt)

        final_answer = ""
        async for chunk in response_generator:
            final_answer += chunk.delta
            yield chunk.delta

        transcript_service.append_turn(
            session_id=session_id,
            user_id=user_id,
            user_msg=user_message,
            ai_msg=final_answer,
            rewritten_query=standalone_query if standalone_query != user_message else None,
        )
        safe_background_task(post_turn_maintenance_service.run(session_id, user_id))

    except Exception as exc:  # noqa: BLE001
        # Full detail to the backend log (provider, status code, body…).
        logger.error("Agent execution failed: %s\n%s", exc, traceback.format_exc())
        # User sees a sentence they can act on (no status codes, no
        # tracebacks). _humanize_exc maps known upstream errors → Chinese.
        yield _humanize_exc(exc)
    finally:
        safe_background_task(
            log_interaction_metrics(
                session_id=session_id,
                user_id=user_id,
                latency=time.time() - start_time,
                prompt_tokens=token_counter.prompt_llm_token_count,
                completion_tokens=token_counter.completion_llm_token_count,
                retrieval_attempted=retrieval_attempted,
                retrieval_hit=retrieval_hit,
            )
        )


__all__ = ["stream_chat_with_agent"]
