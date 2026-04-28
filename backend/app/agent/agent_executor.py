import asyncio
import logging
import time
import traceback
from typing import AsyncGenerator

import tiktoken
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler

from app.agent.rewriter import rewrite_query
from app.agent.router import analyze_intent
from app.rag.embeddings import agent_fast_llm
from app.rag.retriever import query_knowledge_base
from app.services.context_service import context_pipeline
from app.services.interview_state_service import interview_state_service
from app.services.memory_extraction_service import (
    memory_retrieval_service,
    post_turn_maintenance_service,
)
from app.services.telemetry_service import log_interaction_metrics
from app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)

token_counter = TokenCountingHandler(
    tokenizer=tiktoken.get_encoding("cl100k_base").encode,
)
Settings.callback_manager = CallbackManager([token_counter])


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
        transcript_service.ensure_session(session_id, user_id)
        interview_state_service.ensure_state(session_id, user_id)

        rewrite_context = context_pipeline.assemble_rewrite_context(
            session_id=session_id,
            user_id=user_id,
            current_query=user_message,
        )
        standalone_query = await rewrite_query(
            user_message=user_message,
            chat_context=rewrite_context.context_text,
        )

        relevant_memories = await memory_retrieval_service.recall_relevant(
            user_id=user_id,
            query=standalone_query,
        )
        decision = await analyze_intent(standalone_query)
        retrieval_attempted = decision.needs_retrieval

        retrieved_context = ""
        if decision.needs_retrieval and decision.target_sources:
            results = await asyncio.gather(
                *[
                    query_knowledge_base(
                        query_str=decision.search_keywords,
                        source_type=source,
                        user_id=user_id,
                    )
                    for source in decision.target_sources
                ]
            )
            pieces = []
            for source, result in zip(decision.target_sources, results):
                body = result.get("answer", "[SYSTEM_EMPTY_WARNING]")
                pieces.append(f"=== [{source.upper()}] ===\n{body}")
            retrieved_context = "\n".join(pieces)
            retrieval_hit = "[SYSTEM_EMPTY_WARNING]" not in retrieved_context

        answer_context = context_pipeline.assemble_answer_context(
            session_id=session_id,
            user_id=user_id,
            current_query=standalone_query,
            relevant_memories=relevant_memories,
            retrieved_documents=retrieved_context,
        )

        if not decision.needs_retrieval:
            prompt = (
                "You are Interview Copilot, a concise technical interview assistant.\n\n"
                f"{answer_context.context_text}"
            )
            response_generator = await agent_fast_llm.astream_complete(prompt)
        else:
            prompt = (
                "You are Interview Copilot, a concise technical interview assistant.\n"
                "Prefer interview_state over long-term memory when discussing current candidate performance.\n\n"
                f"{answer_context.context_text}"
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
        asyncio.create_task(post_turn_maintenance_service.run(session_id, user_id))

    except Exception as exc:  # noqa: BLE001
        logger.error("Agent execution failed: %s\n%s", exc, traceback.format_exc())
        yield f"系统异常: {exc}"
    finally:
        asyncio.create_task(
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
