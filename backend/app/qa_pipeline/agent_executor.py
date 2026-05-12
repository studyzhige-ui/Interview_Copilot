"""L1 QA orchestrator — ``stream_chat_with_agent``.

Drives a single chat turn through plan → retrieve → answer → persist,
with telemetry and post-turn maintenance running in the background.
"""

import asyncio
import logging
import time
import traceback
from typing import AsyncGenerator

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
        # user_profile: always loaded directly from DB (like hermes USER.md)
        user_profile = memory_retrieval_service.load_user_profile(user_id)

        # interview_fact: vector-searched only when relevant
        memory_task = asyncio.create_task(
            memory_retrieval_service.recall_relevant(
                user_id=user_id,
                query=query_plan.dense_query or standalone_query,
                memory_types=["interview_fact"],
            )
        ) if query_plan.needs_memory_retrieval else None
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
        logger.error("Agent execution failed: %s\n%s", exc, traceback.format_exc())
        yield f"系统异常: {exc}"
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
