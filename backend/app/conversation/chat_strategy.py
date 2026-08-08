"""L1 chat-pipeline strategy — deterministic plan → retrieve → answer.

Hosts the fixed-orchestration single-turn flow. Memory recall,
context assembly, retrieval, persistence, and post-turn maintenance
all live in :class:`~app.conversation.engine.ConversationEngine`;
this strategy only owns the single LLM call that produces the answer
(streaming) plus the prompt-rendering choice between direct and RAG modes.

No tools, no while loop, no compaction — that's the agent strategy's
territory. The chat strategy's whole job is "render the right prompt
and stream one LLM call."
"""

from __future__ import annotations

import logging
import re
from typing import AsyncGenerator

from app.conversation.events import HarnessEvent
from app.conversation.strategy import StrategyContext, StrategyResult
from app.core.llm_client_factory import get_llm_for_role
from app.core.tokens import token_count as _count_tokens
from app.prompts.chat import DIRECT_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT
from app.rag.evidence import check_evidence
from app.services.chat.citation import validate_citations
from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
    context_pipeline,
)

logger = logging.getLogger(__name__)


def _insufficient_evidence_message(query: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", query):
        return "现有资料不足，无法可靠回答这个问题。"
    return "The available sources do not contain enough evidence to answer reliably."


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
        # Render the engine-prepared AssembledContext with the right
        # system-rules branch. No rebuild — the engine already paid
        # for the session-meta read + debrief reference fetch, and
        # rebuilding would duplicate both round-trips.
        assembled: AssembledContext = ctx.assembled

        evidence = (
            check_evidence(
                ctx.search_intents,
                (
                    f"{chunk.get('document_title') or ''}\n{chunk.get('text') or ''}"
                    for chunk in ctx.knowledge_chunks
                ),
            )
            if ctx.needs_knowledge_retrieval and ctx.retrieval_hit
            else None
        )
        if ctx.needs_knowledge_retrieval and (
            not ctx.retrieval_hit or (evidence is not None and not evidence.supported)
        ):
            answer = _insufficient_evidence_message(ctx.user_message)
            yield HarnessEvent.status("现有资料不足", step=0, elapsed_ms=0)
            yield HarnessEvent.text_delta(answer, step=0, elapsed_ms=0)
            result.final_answer = answer
            result.assistant_blocks = [{"type": "text", "text": answer}]
            result.steps_used = 0
            result.completion_tokens = _count_tokens(answer)
            return

        prompt = self.renderer.render_answer_prompt(
            assembled,
            system_prompt=(
                RAG_SYSTEM_PROMPT
                if ctx.needs_knowledge_retrieval
                else DIRECT_SYSTEM_PROMPT
            ),
        )
        yield HarnessEvent.status(
            "正在生成回答...",
            step=0,
            elapsed_ms=0,
        )

        # Final answers always use the model selected by the user. Internal
        # router/worker models are never allowed to answer on the user's behalf.
        llm = get_llm_for_role("primary", user_id=ctx.user_id)
        response_generator = await llm.astream_complete(prompt)

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
        # Post-generation citation check (RAG turns only) — regex, no LLM
        # second pass. Logs warnings for unknown / missing [K#]; the answer
        # text is never rewritten (generation plan §2.5). Only runs when the
        # turn actually had citable sources, so direct chat never warns.
        if ctx.sources:
            validate_citations(
                final_answer,
                ctx.sources,
                retrieval_hit=ctx.retrieval_hit,
            )

        result.final_answer = final_answer
        result.assistant_blocks = [{"type": "text", "text": final_answer}]
        result.steps_used = 1
        # Per-turn token estimate via local tiktoken — no global state,
        # no race with concurrent turns. See module docstring for why
        # we don't use Settings.callback_manager's TokenCountingHandler.
        # Falls back to a heuristic when tiktoken couldn't load.
        result.prompt_tokens = _count_tokens(prompt)
        result.completion_tokens = _count_tokens(final_answer)


__all__ = ["ChatPipelineStrategy"]
