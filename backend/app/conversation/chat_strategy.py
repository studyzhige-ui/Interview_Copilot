"""L1 chat-pipeline strategy — deterministic plan → retrieve → answer.

Hosts the fixed-orchestration single-turn flow that used to live in
``qa_pipeline.agent_executor.stream_chat_with_agent``. Memory recall,
context assembly, retrieval, persistence, and post-turn maintenance
have all moved into :class:`~app.conversation.engine.ConversationEngine`;
this strategy only owns the single LLM call that produces the answer
(streaming) plus the prompt-rendering choice between direct and RAG modes.

No tools, no while loop, no compaction — that's the agent strategy's
territory. The chat strategy's whole job is "render the right prompt
and stream one LLM call."
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator

import tiktoken
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler

from app.conversation.events import HarnessEvent
from app.conversation.strategy import StrategyContext, StrategyResult
from app.rag.embeddings import agent_fast_llm
from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
    context_pipeline,
)

logger = logging.getLogger(__name__)


# LlamaIndex callback that records prompt + completion token counts per
# LLM call. Installed on the global Settings.callback_manager at module
# import (same as the legacy ``qa_pipeline.agent_executor`` did) so the
# next streaming call's usage is captured into the counter. The strategy
# resets the counter at the start of each turn and reads it after the
# stream finishes — same pattern as the old code.
_token_counter = TokenCountingHandler(
    tokenizer=tiktoken.get_encoding("cl100k_base").encode,
)
Settings.callback_manager = CallbackManager([_token_counter])


DIRECT_SYSTEM_RULES = """You are Interview Copilot, a concise technical interview assistant.
Use the provided session state and memories only when relevant. If context is insufficient, say what is missing."""

RAG_SYSTEM_RULES = """You are Interview Copilot, a concise technical interview assistant.
Use retrieved knowledge as evidence and avoid inventing sources."""


class ChatPipelineStrategy:
    """The L1 chat-pipeline execution strategy."""

    name = "chat"

    def __init__(
        self,
        renderer: PromptRenderer | None = None,
    ) -> None:
        self.renderer = renderer or context_pipeline.renderer

    async def execute(
        self,
        ctx: StrategyContext,
        result: StrategyResult,
    ) -> AsyncGenerator[HarnessEvent, None]:
        # Snapshot before/after token counts so we can report exact
        # per-turn usage to ``result`` (and from there to telemetry).
        # The global TokenCountingHandler installed at module load
        # captures every LlamaIndex LLM call.
        _token_counter.reset_counts()

        # Render the engine-prepared AssembledContext with the right
        # system-rules branch. No rebuild — the engine already paid
        # for the session-meta read + debrief reference fetch, and
        # rebuilding would duplicate both round-trips.
        assembled: AssembledContext = ctx.assembled

        if ctx.needs_knowledge_retrieval:
            prompt = self.renderer.render_answer_prompt(
                assembled, system_prompt=RAG_SYSTEM_RULES,
            )
            response_generator = await Settings.llm.astream_complete(prompt)
        else:
            prompt = self.renderer.render_answer_prompt(
                assembled, system_prompt=DIRECT_SYSTEM_RULES,
            )
            response_generator = await agent_fast_llm.astream_complete(prompt)

        yield HarnessEvent.status(
            "正在生成回答...", step=0, elapsed_ms=0,
        )

        final_answer = ""
        async for chunk in response_generator:
            final_answer += chunk.delta
            yield HarnessEvent.text_delta(chunk.delta, step=0, elapsed_ms=0)

        # Engine reads result.final_answer for persistence. We DO NOT
        # also emit ``HarnessEvent.text(final_answer)`` — the L1 wire
        # contract is delta-only, matching the legacy chat-pipeline
        # behaviour. The agent strategy is the one that uses ``text``
        # as a terminator marker, but it only fires after a tool-loop
        # cycle, not after deltas (no double-render risk there).
        result.final_answer = final_answer
        result.assistant_blocks = [{"type": "text", "text": final_answer}]
        result.steps_used = 1
        result.prompt_tokens = _token_counter.prompt_llm_token_count
        result.completion_tokens = _token_counter.completion_llm_token_count


__all__ = ["ChatPipelineStrategy"]
