"""L1 chat-pipeline strategy — deterministic plan → retrieve → answer.

Hosts the fixed-orchestration single-turn flow. Context assembly, retrieval,
persistence, and post-turn maintenance live in
:class:`~app.conversation.engine.ConversationEngine`;
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
from app.conversation.provider_context import compose_provider_context
from app.conversation.strategy import StrategyContext, StrategyResult
from app.core.config import settings
from app.core.llm_client_factory import (
    build_provider_client_for_role as get_llm_for_role,
)
from app.core.model_provider_adapter import ModelProviderAdapter, build_provider_request
from app.core.tokens import token_count as _count_tokens
from app.prompts.chat import DIRECT_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT
from app.rag.grounding.citations import CitationStreamGuard, validate_citations
from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
    context_pipeline,
)
from app.services.chat.model_dispatch_service import (
    durable_model_stream,
    finish_model_dispatch,
    request_fingerprint,
    start_model_dispatch_for_turn,
)

logger = logging.getLogger(__name__)


def _insufficient_evidence_message(query: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", query):
        return "现有资料不足，无法可靠回答这个问题。"
    return "The available sources do not contain enough evidence to answer reliably."


def _explicit_source_failure_message(query: str, failures: tuple[dict, ...]) -> str:
    chinese = bool(re.search(r"[\u4e00-\u9fff]", query))
    lines: list[str] = []
    for failure in failures[:3]:
        identity = str(failure.get("identity") or "URL")[:300]
        detail = str(failure.get("detail") or "read failed")[:300]
        lines.append(
            f"- {identity}：{detail}" if chinese else f"- {identity}: {detail}"
        )
    if chinese:
        return (
            "无法读取你在本轮明确指定的来源，因此没有用搜索摘要或模型常识冒充其内容：\n"
            + "\n".join(lines)
        )
    return (
        "I could not read the source(s) explicitly specified in this turn, so I "
        "did not substitute search snippets or model knowledge for their content:\n"
        + "\n".join(lines)
    )


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

        explicit_failures = tuple(ctx.extras.get("explicit_source_failures") or ())
        if explicit_failures:
            answer = _explicit_source_failure_message(
                ctx.user_message,
                explicit_failures,
            )
            # Successful sibling reads remain represented in the internal
            # status projection, but a blocked answer must not display uncited
            # source cards as if the requested comparison had completed.
            assembled.sources = []
            yield HarnessEvent.status("明确来源读取失败", step=0, elapsed_ms=0)
            yield HarnessEvent.text_delta(answer, step=0, elapsed_ms=0)
            result.final_answer = answer
            result.assistant_blocks = [{"type": "text", "text": answer}]
            result.steps_used = 0
            result.completion_tokens = _count_tokens(answer)
            result.outcome = "blocked"
            return

        requirements = tuple(ctx.extras.get("attachment_execution_requirements") or ())
        if requirements:
            visual = next(
                (
                    item
                    for item in requirements
                    if item.get("kind") == "visual_layout_unavailable"
                ),
                None,
            )
            if visual is not None:
                answer = (
                    "Chat 模式不会执行逐页视觉工具循环，因此不能从文本/OCR 投影"
                    "推断字体、颜色、排版或视觉布局。请切换到 Agent 模式；它会按"
                    "同一来源 identity 调用真实页面视觉工具，无法执行时也会明确说明。"
                )
                yield HarnessEvent.status(
                    "需要 Agent 逐页视觉读取", step=0, elapsed_ms=0
                )
                yield HarnessEvent.text_delta(answer, step=0, elapsed_ms=0)
                result.final_answer = answer
                result.assistant_blocks = [{"type": "text", "text": answer}]
                result.steps_used = 0
                result.completion_tokens = _count_tokens(answer)
                result.outcome = "blocked"
                return
            # Chat has no iterative read_file loop.  A full review that does not
            # fit in the injected projection must switch to Agent instead of
            # silently answering from top-k excerpts.
            answer = (
                "本次完整审阅所需内容超过单次安全上下文范围。请切换到 Agent 模式，"
                "它会按同一来源 identity 分段读完后再给出结论。"
            )
            yield HarnessEvent.status("需要分段完整读取", step=0, elapsed_ms=0)
            yield HarnessEvent.text_delta(answer, step=0, elapsed_ms=0)
            result.final_answer = answer
            result.assistant_blocks = [{"type": "text", "text": answer}]
            result.steps_used = 0
            result.completion_tokens = _count_tokens(answer)
            result.outcome = "blocked"
            return

        if ctx.needs_knowledge_retrieval and not ctx.retrieval_hit:
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
        # Rendering performs the final model-window reconciliation. Evidence
        # eligibility and citation cards must therefore use this exact,
        # post-budget bundle—not the larger pre-render retrieval result.
        if ctx.needs_knowledge_retrieval and not assembled.grounding.supported:
            answer = _insufficient_evidence_message(ctx.user_message)
            assembled.sources = []
            yield HarnessEvent.status("现有资料不足", step=0, elapsed_ms=0)
            yield HarnessEvent.text_delta(answer, step=0, elapsed_ms=0)
            result.final_answer = answer
            result.assistant_blocks = [{"type": "text", "text": answer}]
            result.steps_used = 0
            result.prompt_tokens = _count_tokens(prompt)
            result.completion_tokens = _count_tokens(answer)
            return

        if assembled.sources:
            yield HarnessEvent.sources(assembled.sources, step=0, elapsed_ms=0)
        yield HarnessEvent.status(
            "正在生成回答...",
            step=0,
            elapsed_ms=0,
        )

        # Final answers always use the model selected by the user. Internal
        # router/worker models are never allowed to answer on the user's behalf.
        resolved_model = get_llm_for_role("primary", user_id=ctx.user_id)
        if isinstance(resolved_model, tuple) and len(resolved_model) == 2:
            client, profile = resolved_model
            projection = compose_provider_context(
                assembled,
                renderer=self.renderer,
                system_prompt=(
                    RAG_SYSTEM_PROMPT
                    if ctx.needs_knowledge_retrieval
                    else DIRECT_SYSTEM_PROMPT
                ),
            )
            request = build_provider_request(
                messages=projection.with_leading_system_message(),
                tools=None,
                max_tokens=min(
                    assembled.output_token_reserve,
                    int(getattr(profile, "max_output_tokens", 0) or 0)
                    or assembled.output_token_reserve,
                ),
                temperature=settings.AGENT_TEMPERATURE,
            )
            adapter = ModelProviderAdapter(client=client, profile=profile)
            model_call_id = (
                f"model:{ctx.dispatch_generation}:chat:1" if ctx.turn_id else None
            )
            if model_call_id and ctx.user_pk > 0:
                import asyncio

                await asyncio.to_thread(
                    start_model_dispatch_for_turn,
                    call_id=model_call_id,
                    turn_id=ctx.turn_id,
                    user_id=ctx.user_pk,
                    dispatch_generation=ctx.dispatch_generation,
                    provider=str(getattr(profile, "provider", "unknown") or "unknown"),
                    model=str(getattr(profile, "model", "unknown") or "unknown"),
                    fingerprint=request_fingerprint(
                        messages=request.messages,
                        tools=request.tools,
                    ),
                )
            try:
                provider_stream = await adapter.start_stream(request)
            except BaseException as exc:
                if model_call_id:
                    import asyncio

                    await asyncio.to_thread(
                        finish_model_dispatch,
                        turn_id=ctx.turn_id,
                        call_id=model_call_id,
                        dispatch_generation=ctx.dispatch_generation,
                        status=(
                            "cancelled"
                            if isinstance(exc, asyncio.CancelledError)
                            else "failed"
                        ),
                        error_code=type(exc).__name__,
                    )
                raise
            response_generator = durable_model_stream(
                provider_stream,
                turn_id=ctx.turn_id,
                call_id=model_call_id,
                dispatch_generation=ctx.dispatch_generation,
            )
            result.provider_id = str(getattr(profile, "provider", "") or "")
            result.prompt_cache_supported = adapter.prompt_cache_supported
            result.prompt_cache_enabled = adapter.prompt_cache_enabled
        else:
            # Focused tests and older injected LlamaIndex doubles use this
            # compatibility seam. Production role resolution returns a native
            # ``(client, profile)`` tuple and never enters this branch.
            response_generator = await resolved_model.astream_complete(
                prompt,
                max_tokens=assembled.output_token_reserve,
            )

        final_answer = ""
        citation_guard = (
            CitationStreamGuard(assembled.sources) if assembled.sources else None
        )
        async for chunk in response_generator:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                result.prompt_tokens += int(usage.prompt_tokens)
                result.completion_tokens += int(usage.completion_tokens)
                result.cache_read_tokens += int(usage.cache_read_tokens)
                result.cache_creation_tokens += int(usage.cache_creation_tokens)
            raw_delta = (
                chunk.text_delta
                if hasattr(chunk, "text_delta")
                else getattr(chunk, "delta", "")
            )
            deltas = citation_guard.feed(raw_delta) if citation_guard else [raw_delta]
            for delta in deltas:
                final_answer += delta
                yield HarnessEvent.text_delta(delta, step=0, elapsed_ms=0)
        if citation_guard:
            tail = citation_guard.flush()
            if tail:
                final_answer += tail
                yield HarnessEvent.text_delta(tail, step=0, elapsed_ms=0)

        # Engine reads result.final_answer for persistence. We DO NOT
        # also emit ``HarnessEvent.text(final_answer)`` — the L1 wire
        # contract is delta-only. The agent strategy is the one that uses ``text``
        # as a terminator marker, but it only fires after a tool-loop
        # cycle, not after deltas (no double-render risk there).
        # Post-generation citation check (RAG turns only) — regex, no LLM
        # second pass. Logs warnings for unknown / missing [K#]; the answer
        # text is never rewritten (generation plan §2.5). Only runs when the
        # turn actually had citable sources, so direct chat never warns.
        if assembled.sources:
            citation_report = validate_citations(
                final_answer,
                assembled.sources,
                retrieval_hit=ctx.retrieval_hit,
            )
            removed_refs = (
                list(dict.fromkeys(citation_guard.removed_refs))
                if citation_guard
                else []
            )
            if not citation_report.ok or removed_refs:
                logger.warning(
                    "RAG citation validation failed: invalid=%s missing=%s",
                    [*citation_report.invalid_refs, *removed_refs],
                    citation_report.missing_citation,
                )
            result.extras["citation_report"] = {
                "valid_refs": citation_report.valid_refs,
                "invalid_refs": citation_report.invalid_refs,
                "removed_invalid_refs": removed_refs,
                "missing_citation": citation_report.missing_citation,
            }

        result.final_answer = final_answer
        result.assistant_blocks = [{"type": "text", "text": final_answer}]
        result.steps_used = 1
        # Per-turn token estimate via local tiktoken — no global state,
        # no race with concurrent turns. See module docstring for why
        # we don't use Settings.callback_manager's TokenCountingHandler.
        # Falls back to a heuristic when tiktoken couldn't load.
        if result.prompt_tokens <= 0:
            result.prompt_tokens = _count_tokens(prompt)
        if result.completion_tokens <= 0:
            result.completion_tokens = _count_tokens(final_answer)


__all__ = ["ChatPipelineStrategy"]
