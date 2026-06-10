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

import tiktoken
from llama_index.core import Settings

from app.conversation.events import HarnessEvent
from app.conversation.strategy import StrategyContext, StrategyResult
from app.rag.embeddings import agent_fast_llm
from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
    context_pipeline,
)

logger = logging.getLogger(__name__)


# Per-turn token counting via a module-level tiktoken encoder.
#
# Pre-fix this module installed a single ``TokenCountingHandler`` on
# the global ``Settings.callback_manager`` at import time, then reset
# it at the start of every turn and read its counters at the end. That
# was racy: two concurrent ``/chat/sse`` turns would call
# ``reset_counts()`` mid-stream, wiping each other's accumulated
# counts. Result: telemetry showed each L1 turn reporting the other's
# tokens (or zero), and any code that *also* relied on the global
# callback manager (the planner, realtime extraction) would silently
# share a noisy counter.
#
# Local counting via tiktoken removes both the race AND the global
# mutation. The numbers are APPROXIMATE — ``cl100k_base`` is OpenAI's
# GPT-3.5/4 tokenizer; the L1 default provider is DeepSeek, whose own
# BPE diverges 10-15% on Chinese-heavy prompts. For race-free
# telemetry that's fine; for exact billing you'd want the response's
# ``raw.usage`` when the SDK exposes it (the agent strategy reads
# ``chunk.usage.prompt_tokens`` directly — chat strategy's streaming
# completion shape doesn't surface usage so we tokenize locally).
#
# Hardened against offline boot: ``tiktoken.get_encoding`` downloads
# BPE data from OpenAI's CDN on first call when no local cache file
# exists. On a brand-new deploy with no network access, this raises
# at import time — which would crash the entire FastAPI app boot
# (every chat-router import path imports this module transitively).
# The try/except falls back to a None sentinel; ``execute()`` checks
# for it and uses a heuristic char-based estimate as a degraded mode.
try:
    _TIKTOKEN_ENC: tiktoken.Encoding | None = tiktoken.get_encoding("cl100k_base")
except Exception as _exc:  # noqa: BLE001 — network / disk / version
    logger.warning(
        "tiktoken encoder unavailable at import (%s); token counts "
        "will use a char-length heuristic instead", _exc,
    )
    _TIKTOKEN_ENC = None


def _count_tokens(text: str) -> int:
    """Tiktoken count when available; else a ~3-chars-per-token
    heuristic (typical English / mixed-language ratio; coarse but
    non-zero so telemetry isn't blank in degraded mode)."""
    if _TIKTOKEN_ENC is not None:
        return len(_TIKTOKEN_ENC.encode(text))
    return max(1, len(text) // 3) if text else 0


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
            response_generator = await Settings.llm.astream_complete(prompt)
        else:
            prompt = self.renderer.render_answer_prompt(
                assembled, system_prompt=DIRECT_SYSTEM_PROMPT,
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
        # Post-generation citation check (RAG turns only) — regex, no LLM
        # second pass. Logs warnings for unknown / missing [K#]; the answer
        # text is never rewritten (generation plan §2.5). Only runs when the
        # turn actually had citable sources, so direct chat never warns.
        if ctx.sources:
            from app.services.chat.citation import validate_citations
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
