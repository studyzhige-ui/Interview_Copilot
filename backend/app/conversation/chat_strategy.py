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
from typing import AsyncGenerator

from llama_index.core import Settings

from app.conversation.events import HarnessEvent
from app.conversation.strategy import StrategyContext, StrategyResult
from app.core.llm_client_factory import get_llm_for_role
from app.services.chat.citation import validate_citations
from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
    context_pipeline,
)

logger = logging.getLogger(__name__)


# Token counting: the canonical tokenizer lives in app.core.tokens — a
# second module-level tiktoken encoder here duplicated init cost and could
# drift on encoding choice (AGT-6).
from app.core.tokens import token_count as _count_tokens


DIRECT_SYSTEM_PROMPT = """You are Interview Copilot, a concise technical interview assistant.
Use the provided session state and memories only when relevant. If context is insufficient, say what is missing."""

# L1 RAG answer contract (generation plan §2.2): names the only citable slot,
# requires [K#] citations for retrieved-knowledge claims, defines partial-
# answer / refusal behaviour, and forbids leaking internal retrieval details.
RAG_SYSTEM_RULES = """You are Interview Copilot, a concise technical interview assistant.

Context rules:
- [Retrieved Context] is the only citable knowledge evidence.
- [Memory], [Recent Turns], and [Record Context] can help understand the user and conversation, but they are not citable knowledge sources.
- Use retrieved evidence only when it is relevant to the user's current question.
- Do not invent sources, document names, pages, or citation ids.

Answer rules:
- For factual claims based on retrieved knowledge, cite the supporting chunk with [K#].
- If multiple chunks support the same point, cite all relevant ids like [K1][K3].
- If the retrieved context is insufficient, say what is missing.
- If only part of the question is supported, answer that part and clearly mark the unsupported part.
- If no retrieved evidence is relevant, do not pretend it is supported.
- Never mention internal retrieval, planner failure, reranking, or system implementation details to the user.

Style:
- Answer in Chinese unless the user asks otherwise.
- Be concise, structured, and interview-oriented."""


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

        if ctx.needs_knowledge_retrieval:
            prompt = self.renderer.render_answer_prompt(
                assembled, system_prompt=RAG_SYSTEM_RULES,
            )
            llm = get_llm_for_role("primary", user_id=ctx.user_id)
            response_generator = await llm.astream_complete(prompt)
        else:
            prompt = self.renderer.render_answer_prompt(
                assembled, system_prompt=DIRECT_SYSTEM_PROMPT,
            )
            llm = get_llm_for_role("utility", user_id=ctx.user_id)
            response_generator = await llm.astream_complete(prompt)

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
        # Post-generation citation check (RAG turns only) — regex, no LLM
        # second pass. Logs warnings for unknown / missing [K#]; the answer
        # text is never rewritten (generation plan §2.5). Only runs when the
        # turn actually had citable sources, so direct chat never warns.
        if ctx.sources:
            validate_citations(
                final_answer, ctx.sources, retrieval_hit=ctx.retrieval_hit,
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
