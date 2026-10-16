"""L2 ReAct agent strategy — the autonomous tool-calling loop.

Hosts the ``while True:`` agent loop that used to live in
``agent_runtime.query_engine.QueryEngine._query_loop``. Everything that
was multi-turn outer-shell concern (memory recall, context assembly,
transcript persistence, post-turn maintenance) is now in
:class:`~app.conversation.engine.ConversationEngine`; this strategy
only handles the per-turn execution.

The strategy:
  * builds the initial messages array from the prepared context
  * drives the LLM↔tool ReAct loop until a final answer or lifecycle stop
  * tracks token and tool usage as telemetry (engine reads back via
    :class:`StrategyResult`)
  * emits ``HarnessEvent`` for SSE
  * builds the Anthropic-style ``content_blocks_json`` chain
    (interleaved text/tool_use/tool_result) so the engine can persist
    it for the Claude-Code-style folded-card frontend UX

Developer trace observability lives in LangSmith (every LLM call is
auto-captured by ``wrap_openai`` in ``core/llm_tracing.py``). The
former ``agent_runs`` + ``agent_steps`` persistence was deleted in
the audit cleanup — LangSmith covers the same surface with a UI for
free, and the user-facing tool cards still come from
``conversation_messages.content_blocks_json``.
"""

from __future__ import annotations

from dataclasses import replace
from app.usage import runtime as usage_runtime
from app.usage.service import reservation_id

import asyncio
import logging
import time
from typing import Any, AsyncGenerator


# Trigger tool self-registration on first import.
import app.agent_runtime.builtin_tools  # noqa: F401
from app.agent_runtime.context_compactor import ActiveTurnContextReducer
from app.agent_runtime.react_agent import (
    AgentRunState,
)
from app.agent_runtime.retry_utils import call_with_retry
from app.agent_runtime.tool_call_executor import (
    cancel_deferred_tool_calls,
    persist_turn_budget,
    reject_waiting_tool_call,
)
from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
from app.agent_runtime.tool_registry import safe_json_dumps
from app.agent_runtime.turn_tool_catalog import TurnToolCatalog
from app.conversation.agent_turn_state import (
    _append_replayed_tool,
    _current_task_content_with_plan,
    _load_agent_task_snapshot,
    _load_completed_tool_tail,
    _load_tool_resume_snapshot,
)
from app.conversation.events import HarnessEvent
from app.conversation.tool_batch import execute_tool_batch
from app.core.context_messages import runtime_control_message
from app.conversation.strategy import StrategyContext, StrategyResult
from app.core.config import settings
from app.core.error_messages import humanize_error
from app.core.llm_client_factory import (
    build_provider_client_for_role,
)
from app.core.model_provider_adapter import (
    ModelProviderAdapter,
    ProviderStreamEvent,
    build_provider_request,
    normalize_openai_chunk,
)
from app.prompts.agent import agent_system_prompt_for_runtime
from app.conversation.application.model_dispatch_service import ModelOutcomeUnknownError
from app.conversation.application.model_dispatch_service import dispatch_failure_status
from app.conversation.application.model_dispatch_service import durable_model_stream
from app.conversation.application.model_dispatch_service import finish_model_dispatch
from app.conversation.application.model_dispatch_service import request_fingerprint
from app.conversation.application.model_dispatch_service import (
    start_model_dispatch_for_turn,
)

logger = logging.getLogger(__name__)

_LOCAL_RECOVERY_ATTEMPTS = 3


def _build_graceful_fallback(
    blocks: list[dict[str, Any]],
    error_message: str,
) -> str:
    """Construct a user-facing message when the agent loop crashed.

    Pre-fix behaviour: any exception in the inner loop produced a
    flat "Agent 执行失败，请稍后重试" string, discarding every tool
    call's worth of context the user just watched run. That's the
    failure mode the user called out — 4 tools fired, then a generic
    dead-end message. New behaviour:

    1. If any text block was emitted before the crash, surface it
       (the LLM did say SOMETHING useful).
    2. Summarise which tools ran and what they returned (success /
       empty / error) — at minimum the user knows what was attempted.
    3. Close with a friendly suggestion + the raw error in a small
       debug note (not at the top, not the headline).

    The intent: never leave the user with a content-less "I failed"
    bubble. There's always something to say.
    """
    parts: list[str] = []
    text_blocks = [b for b in blocks if b.get("type") == "text" and b.get("text")]
    tool_use_blocks = [b for b in blocks if b.get("type") == "tool_use"]
    tool_result_blocks = [b for b in blocks if b.get("type") == "tool_result"]

    if text_blocks:
        # The LLM produced reasoning text before crashing — that's
        # likely the bulk of a useful answer. ``str()`` wrap is a
        # defensive guard against an unexpected non-string ``text``
        # field (the loop itself only ever writes strings, but block
        # shapes can drift over time).
        parts.append(str(text_blocks[-1].get("text") or "").strip())

    if tool_use_blocks:
        tool_names = ", ".join(sorted({b.get("name", "?") for b in tool_use_blocks}))
        empty_or_error = sum(
            1
            for b in tool_result_blocks
            if b.get("is_error")
            or "未找到" in (b.get("summary") or "")
            or "0 条" in (b.get("summary") or "")
            or "⊘" in (b.get("summary") or "")
        )
        parts.append(
            f"\n\n---\n本轮我已尝试调用：{tool_names}"
            + (f"（其中 {empty_or_error} 个未返回有效数据）" if empty_or_error else "")
            + "。"
        )

    # Friendly close — never blame the user.
    parts.append(
        "\n\n执行链路中途断开，没能完整跑完。可以再发一次相同的问题让我重试，"
        "或者把问题拆得更具体一点 —— 比如直接给关键词 / 公司名 / 技术方向，"
        "通常能跳过工具直接答。"
    )

    # Last: a small dev-debug line (kept short — users will see it
    # but it's not the headline). Strip backticks so an error message
    # containing them doesn't break the surrounding markdown code-span.
    safe_err = (error_message or "")[:200].replace("`", "'")
    parts.append(f"\n\n_错误详情_: `{safe_err}`")

    body = "".join(parts).strip()
    return body or "执行过程中断，请稍后重试。"


class AgentLoopStrategy:
    """The L2 ReAct execution strategy."""

    name = "agent"

    def __init__(self) -> None:
        # Subsystems are constructed lazily in execute() so the strategy
        # object itself is cheap to instantiate (per-turn).
        pass

    # ── Public entry: execute one turn ────────────────────────────

    async def execute(
        self,
        ctx: StrategyContext,
        result: StrategyResult,
    ) -> AsyncGenerator[HarnessEvent, None]:
        # Attachment sources are assembled before the loop through the same
        # GroundingBuilder used by L1 RAG. Surface them immediately;
        # the engine also persists the identical source list on completion.
        # ── Per-turn state ────────────────────────────────────────
        budget = AgentRunState(started_at=time.perf_counter())
        client, profile = await build_provider_client_for_role(
            "primary",
            user_id=ctx.user_id,
        )
        provider_adapter = ModelProviderAdapter(client=client, profile=profile)
        result.provider_id = str(getattr(profile, "provider", "") or "")
        result.prompt_cache_supported = provider_adapter.prompt_cache_supported
        result.prompt_cache_enabled = provider_adapter.prompt_cache_enabled
        if not getattr(profile, "supports_function_calling", True):
            raise ValueError(
                "当前回答模型不支持工具调用，请在模型页面选择支持 Function Calling 的模型。"
            )
        tool_catalog = await TurnToolCatalog.create(
            ctx.user_id,
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            builtin_allowlist=ctx.extras.get("builtin_tool_allowlist"),
            include_deferred=not bool(ctx.extras.get("unattended_automation")),
            runtime_profile=ctx.runtime_profile,
            pinned_skill_refs=ctx.extras.get("persistent_task_skill_refs"),
        )
        activation_errors = tuple(getattr(tool_catalog, "activation_errors", ()))
        if activation_errors:
            detail = "; ".join(activation_errors)
            answer = (
                "当前任务绑定的 Skill 已不可用或版本不兼容，本轮已安全阻塞，"
                "没有静默替换工作流。请检查 Skill 的启用状态、版本和所需工具。"
            )
            result.outcome = "blocked"
            result.stop_reason = "skill_activation_blocked"
            result.final_answer = answer
            result.assistant_blocks = [{"type": "text", "text": answer}]
            result.extras["skill_activation_errors"] = list(activation_errors)
            yield HarnessEvent.error(
                f"{answer} ({detail})",
                step=0,
                elapsed_ms=0,
            )
            return
        await persist_turn_budget(
            ctx.turn_id,
            budget.to_dict(),
        )
        # Developer trace observability is handled by LangSmith
        # (``wrap_openai`` in core/llm_tracing.py captures every LLM
        # call automatically). User-facing tool cards come from the
        # ``content_blocks_json`` chain we build below in ``blocks``
        # and hand back via ``result.assistant_blocks`` for the
        # engine to persist on ``conversation_messages``.

        # Build the agent's context through the SAME shared pipeline as L1
        # chat.  Concrete schemas are carried only by the provider's tool
        # parameter; the system prompt contains stable rules plus compact
        # optional guidance/discovery metadata, never a duplicate schema.
        #
        # ``current_input`` is skipped here and sent as the user message
        # instead, so the model has a user turn to answer and the loop can
        # append assistant/tool turns after it.
        from app.conversation.application.context_assembly_pipeline import (
            prompt_renderer,
        )

        runtime_prompt = agent_system_prompt_for_runtime(ctx.runtime_profile)
        agent_system_prompt = runtime_prompt
        tool_schemas = tool_catalog.get_openai_schemas()
        history_messages: list[dict[str, Any]] = []
        if ctx.assembled is not None:
            # Only stable rules stay in the system prefix. The lossy summary
            # is the first chronological data message; prior exact turns
            # follow it, and per-turn product/RAG data stays beside the current
            # user input.
            from app.conversation.context_manager import prepare

            projection = await prepare(
                ctx.assembled,
                renderer=prompt_renderer,
                system_prompt=agent_system_prompt,
                tool_schemas=tool_schemas,
                client=client,
                profile=profile,
            )
            system_block = projection.system
            history_messages.extend(projection.messages[:-1])
            current_task_content = str(projection.messages[-1]["content"])
            if ctx.assembled.sources:
                yield HarnessEvent.sources(ctx.assembled.sources, step=0, elapsed_ms=0)
        else:
            system_block = agent_system_prompt
            current_task_content = ctx.user_message
        base_current_task_content = current_task_content
        catalog_guidance = tool_catalog.format_prompt()
        if catalog_guidance:
            history_messages.append(
                runtime_control_message("tool_catalog", catalog_guidance)
            )
        render_activated_skills = getattr(
            tool_catalog, "render_activated_skills", lambda: ""
        )
        activated_skill_instructions = render_activated_skills()
        if activated_skill_instructions:
            history_messages.append(
                runtime_control_message(
                    "activated_skill_projection",
                    activated_skill_instructions,
                )
            )
        current_task_message: dict[str, Any] = {
            "role": "user",
            "content": base_current_task_content,
            "_context": {"kind": "user", "id": f"turn:{ctx.turn_id or 'current'}"},
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_block},
            *history_messages,
            current_task_message,
        ]
        compactor = ActiveTurnContextReducer(
            profile=profile,
            user_id=ctx.user_id,
            task_anchor=current_task_message,
            tool_schemas=tool_schemas,
            turn_id=ctx.turn_id,
            output_tokens=min(
                settings.AGENT_MAX_RESPONSE_TOKENS, profile.max_output_tokens
            ),
        )
        compactor.client = client
        compactor.assembled = ctx.assembled
        compactor.dispatch_generation = ctx.dispatch_generation
        # Only this turn's contextual data is re-injected after compaction.
        from app.conversation.context_window import kind

        compactor.initial_context = []
        for historical in reversed(history_messages):
            if kind(historical) in {"user", "assistant", "tool", "summary"}:
                break
            compactor.initial_context.insert(0, historical)
        covered_call_ids: set[str] = set()
        if ctx.turn_id and ctx.dispatch_generation > 1:
            from app.conversation import context_store

            checkpoint = await asyncio.to_thread(
                context_store.load, ctx.session_id, scope=ctx.turn_id
            )
            if checkpoint:
                compactor.checkpoint_version = checkpoint["version"]
                covered_call_ids = set(checkpoint["state"].get("covered_call_ids", []))
                compactor.covered_call_ids = set(covered_call_ids)
                messages[:] = [
                    {"role": "system", "content": system_block},
                    *checkpoint["state"]["messages"],
                ]
                compactor.task_anchor = next(
                    (
                        m
                        for m in messages
                        if m.get("_context", {}).get("id") == f"turn:{ctx.turn_id}"
                    ),
                    current_task_message,
                )
                if compactor.task_anchor is current_task_message:
                    messages.append(current_task_message)
                # Current owner reads supersede any contextual facts retained
                # by the checkpoint; the actual user anchor remains unchanged.
                messages.extend(compactor.initial_context)

        # Accumulated Anthropic-style content blocks for the final
        # assistant turn. Built up as the loop encounters text / tool
        # calls / tool results so the persisted message faithfully
        # replays the same UX the frontend showed live.
        blocks: list[dict[str, Any]] = []

        # A resolved Interaction resumes the original Tool Call rather than
        # asking the model to invent a replacement call. Rebuild the durable
        # completed prefix, then execute/reject exactly the waiting identity.
        resume = (
            await asyncio.to_thread(
                _load_tool_resume_snapshot,
                ctx.turn_id,
                tool_catalog.user_pk,
            )
            if ctx.dispatch_generation > 1
            else None
        )
        if resume is None and ctx.turn_id and ctx.dispatch_generation > 1:
            for prior_call in await asyncio.to_thread(
                _load_completed_tool_tail, ctx.turn_id, tool_catalog.user_pk
            ):
                _append_replayed_tool(
                    [] if str(prior_call["call_id"]) in covered_call_ids else messages,
                    blocks,
                    prior_call,
                )
                budget.tool_call_ids.add(str(prior_call["call_id"]))
        if resume is not None:
            for prior_call in resume["prior"]:
                _append_replayed_tool(
                    [] if str(prior_call["call_id"]) in covered_call_ids else messages,
                    blocks,
                    prior_call,
                )
                budget.tool_call_ids.add(str(prior_call["call_id"]))
            waiting_call = dict(resume["waiting"])
            waiting_id = str(waiting_call["call_id"])
            suspended_calls = [dict(call) for call in resume.get("suspended") or []]
            if (
                resume["resolution_status"] == "rejected"
                and resume.get("interaction_kind") != "fact_confirmation"
            ):
                # A fact rejection is itself a domain decision: run the original
                # thin adapter so the candidate reaches its canonical rejected state.
                rejected = await asyncio.to_thread(
                    reject_waiting_tool_call,
                    call_id=waiting_id,
                    turn_id=str(ctx.turn_id),
                    dispatch_generation=ctx.dispatch_generation,
                    reason=str(
                        (resume.get("resolution") or {}).get("reason", "user_rejected")
                    ),
                )
                cancelled = await asyncio.to_thread(
                    cancel_deferred_tool_calls,
                    turn_id=str(ctx.turn_id),
                    dispatch_generation=ctx.dispatch_generation,
                    blocked_by_call_id=waiting_id,
                )
                cancelled_by_id = {str(call["call_id"]): call for call in cancelled}
                for call in suspended_calls:
                    call_id = str(call["call_id"])
                    replay = (
                        {**waiting_call, "result": rejected, "status": "denied"}
                        if call_id == waiting_id
                        else cancelled_by_id.get(call_id)
                    )
                    if replay is not None:
                        replay = {**replay, "turn_id": ctx.turn_id}
                        _append_replayed_tool(messages, blocks, replay)
                        budget.tool_call_ids.add(call_id)
            else:
                # Connection/readiness resolution only proves that prerequisite;
                # it never doubles as approval for the concrete effect.
                if resume.get("interaction_kind") == "approval":
                    ctx.extras["confirmed_tool_call_id"] = waiting_id
                ctx.extras["resume_tool_call_id"] = waiting_id
                ctx.extras["resume_tool_call_ids"] = {
                    str(call["call_id"]) for call in suspended_calls
                }
                resume_calls = [
                    _ToolCallAccumulator(
                        id=str(call["call_id"]),
                        name=str(call["tool_name"]),
                        arguments=safe_json_dumps(call.get("arguments") or {}),
                    )
                    for call in suspended_calls
                ]
                async for event in execute_tool_batch(
                    ctx=ctx,
                    messages=messages,
                    blocks=blocks,
                    tool_calls_acc=resume_calls,
                    assistant_content="",
                    reasoning_content="",
                    budget=budget,
                    tool_catalog=tool_catalog,
                ):
                    yield event
                ensure_bindings = getattr(
                    tool_catalog, "ensure_active_skill_bindings", None
                )
                if ensure_bindings is not None:
                    await ensure_bindings()
                schema_getter = getattr(tool_catalog, "get_openai_schemas", None)
                refreshed_schemas = (
                    schema_getter() if schema_getter is not None else tool_schemas
                )
                if refreshed_schemas != tool_schemas:
                    tool_schemas[:] = refreshed_schemas
                    compactor.tool_schemas = list(refreshed_schemas)

        final_answer = ""
        ctx.extras.pop("_terminal_outcome", None)

        try:
            async with asyncio.timeout(settings.AGENT_RUN_TIMEOUT_SECONDS):
                if not ctx.extras.get("interaction_required"):
                    async for event in self._loop(
                        ctx=ctx,
                        messages=messages,
                        blocks=blocks,
                        budget=budget,
                        client=client,
                        profile=profile,
                        compactor=compactor,
                        tool_catalog=tool_catalog,
                        tool_schemas=tool_schemas,
                        base_task_content=base_current_task_content,
                    ):
                        if event.type.value == "text":
                            final_answer = event.data.get("content", "")
                        yield event
        except TimeoutError:
            budget.stop_reason = "resource_time_limit"
            ctx.extras["_terminal_outcome"] = "blocked"
            final_answer = "本轮已达到部署允许的执行时长，现有结果已保留。你可以缩小任务范围后继续。"
            yield HarnessEvent.text(
                final_answer,
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
            )
        except Exception as exc:
            logger.error("AgentLoopStrategy crashed: %s", exc)
            # Surface the failure to the LIVE stream as an actionable error.
            # THE BUG this fixes: pre-fix the except only built a fallback
            # into ``result`` (persisted) and never *yielded* anything, so a
            # clean API failure — e.g. a 402 "insufficient balance" on the
            # very first LLM call — left the user staring at an empty turn
            # with no idea what broke or how to fix it. ``humanize_error``
            # is the same translator the L1 chat path uses via the engine,
            # so the wording is identical regardless of which path failed.
            yield HarnessEvent.error(
                humanize_error(exc),
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
            )
            # Still build the graceful partial answer for the PERSISTED
            # transcript so the tool work the user watched isn't lost on
            # reload. We deliberately don't re-raise: re-raising would route
            # through the engine's last-resort catch (a second error event)
            # and skip persistence of this partial answer.
            final_answer = _build_graceful_fallback(
                blocks=blocks,
                error_message=str(exc),
            )
            # Mark the turn degraded so callers can distinguish a partial
            # answer from a clean completion.
            result.extras["degraded"] = True
            ctx.extras["_terminal_outcome"] = "failed"

        if ctx.extras.get("interaction_required"):
            result.outcome = "waiting"
            result.final_answer = ""
            result.assistant_blocks = blocks
            result.prompt_tokens = budget.prompt_tokens
            result.completion_tokens = budget.completion_tokens
            result.cache_read_tokens = budget.cache_read_tokens
            result.cache_creation_tokens = budget.cache_creation_tokens
            result.tool_calls = budget.tool_calls
            result.steps_used = budget.steps
            result.stop_reason = "waiting"
            await persist_turn_budget(
                ctx.turn_id,
                {**budget.to_dict(), "stop_reason": "waiting"},
            )
            yield HarnessEvent.budget(
                budget.to_dict(),
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
            )
            return

        # Ensure a trailing text block exists (so the persisted message
        # always carries a final answer, including a context-window stop).
        if not final_answer:
            final_answer = (
                "上下文窗口已耗尽，本轮已保留现有执行结果。"
                if budget.stop_reason == "context_window_exhausted"
                else "Agent 无法生成最终回答。"
            )
            blocks.append({"type": "text", "text": final_answer})
            # live == replay (AGT-5): a synthetic tail (context stop / crash
            # fallback) used to exist only in the persisted blocks — the
            # live viewer saw the stream just... end.
            yield HarnessEvent.text(
                final_answer,
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
            )
        elif (
            not blocks
            or blocks[-1].get("type") != "text"
            or blocks[-1].get("text") != final_answer
        ):
            blocks.append({"type": "text", "text": final_answer})

        result.final_answer = final_answer
        result.extras["context_messages"] = [
            *messages,
            {"role": "assistant", "content": final_answer},
        ]
        result.assistant_blocks = blocks
        result.prompt_tokens = budget.prompt_tokens
        result.completion_tokens = budget.completion_tokens
        result.cache_read_tokens = budget.cache_read_tokens
        result.cache_creation_tokens = budget.cache_creation_tokens
        result.tool_calls = budget.tool_calls
        result.steps_used = budget.steps
        result.stop_reason = budget.stop_reason
        result.outcome = str(ctx.extras.get("_terminal_outcome") or "completed")
        await persist_turn_budget(
            ctx.turn_id,
            {
                **budget.to_dict(),
                "stop_reason": budget.stop_reason,
            },
        )

        # Final usage event. The legacy wire name remains ``budget`` for
        # compatibility; it contains observations only, never execution caps.
        # LangSmith
        # captures the same fields via the OpenAI wrap, but the FE
        # surfaces budget in-band on the SSE stream so the chat panel
        # can render token/step badges without a trace-service call.
        yield HarnessEvent.budget(
            budget.to_dict(),
            step=budget.steps,
            elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
        )

    # ── Inner loop ────────────────────────────────────────────────

    async def _loop(
        self,
        *,
        ctx: StrategyContext,
        messages: list[dict[str, Any]],
        blocks: list[dict[str, Any]],
        budget: AgentRunState,
        client: Any,
        profile: Any,
        compactor: ActiveTurnContextReducer,
        tool_catalog: TurnToolCatalog,
        tool_schemas: list[dict[str, Any]],
        base_task_content: str,
    ) -> AsyncGenerator[HarnessEvent, None]:
        # Track which text we've already emitted as a block so the
        # final pass doesn't double-count.
        pending_text_for_block = ""
        incomplete_candidate_attempts = 0
        empty_response_attempts = 0

        while True:
            if budget.total_tokens >= settings.AGENT_RUN_MAX_TOTAL_TOKENS:
                budget.stop_reason = "resource_token_limit"
                ctx.extras["_terminal_outcome"] = "blocked"
                yield HarnessEvent.text(
                    "本轮已达到部署允许的模型用量，现有结果已保留。你可以缩小任务范围后继续。",
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )
                return
            budget.consume_step()

            # AgentTask is durable runtime state, not a lossy compaction
            # summary. Reload it at each model boundary and keep it before the
            # exact current-user content inside the preserved task anchor.
            task_snapshot = await asyncio.to_thread(
                _load_agent_task_snapshot,
                ctx.turn_id,
                tool_catalog.user_pk,
            )
            task_anchor = getattr(compactor, "task_anchor", None)
            if isinstance(task_anchor, dict):
                # Runtime changes append after the stable history prefix. They
                # never rewrite the user's intent or grant summary authority.
                runtime_state = _current_task_content_with_plan("", task_snapshot)
                compactor.update_runtime_state(messages, runtime_state)

            # Proactive compaction: self-measure the prompt, run the cheap
            # pre-pass if it's over the threshold, and stop cleanly if the
            # result still sits at the blocking limit (a doomed LLM call).
            messages[:], at_blocking_limit = await compactor.compress(messages)
            if at_blocking_limit:
                budget.stop_reason = "context_window_exhausted"
                ctx.extras["_terminal_outcome"] = "blocked"
                yield HarnessEvent.error(
                    "上下文窗口即将耗尽，停止执行。请缩小目标范围后重试。",
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )
                break

            stream, _ = await self._call_llm_stream(
                client=client,
                profile=profile,
                messages=messages,
                tool_schemas=tool_schemas,
                compactor=compactor,
                budget=budget,
                turn_id=ctx.turn_id,
                user_pk=tool_catalog.user_pk,
                dispatch_generation=ctx.dispatch_generation,
                model_step=budget.steps,
            )

            assistant_content = ""
            tool_calls_acc: list[_ToolCallAccumulator] = []
            # Thinking-mode reasoning trace must round-trip back to the
            # API on the next assistant message — accumulate it here
            # and pass to ``_execute_tools`` which writes the message.
            reasoning_acc: list[str] = []
            request_messages = list(messages)

            async for ev in self._consume_stream(
                stream,
                budget,
                tool_calls_acc,
                reasoning_acc,
                compactor=compactor,
                request_messages=request_messages,
            ):
                if isinstance(ev, HarnessEvent):
                    yield ev
                elif isinstance(ev, str):
                    assistant_content += ev

            compactor.reset_circuit_breaker()

            # If the model emitted any text in this turn (whether it
            # ends in tool_calls or final answer), capture it as a
            # block before any tool blocks are appended. This keeps
            # the storyline order: text → tools → text → tools → text.
            if assistant_content:
                empty_response_attempts = 0
                pending_text_for_block += assistant_content
                if tool_calls_acc:
                    blocks.append(
                        {
                            "type": "text",
                            "text": pending_text_for_block.strip(),
                        }
                    )
                    pending_text_for_block = ""

            if tool_calls_acc:
                empty_response_attempts = 0
                async for ev in execute_tool_batch(
                    ctx=ctx,
                    messages=messages,
                    blocks=blocks,
                    tool_calls_acc=tool_calls_acc,
                    assistant_content=assistant_content,
                    reasoning_content="".join(reasoning_acc),
                    budget=budget,
                    tool_catalog=tool_catalog,
                ):
                    yield ev
                ensure_bindings = getattr(
                    tool_catalog, "ensure_active_skill_bindings", None
                )
                if ensure_bindings is not None:
                    await ensure_bindings()
                schema_getter = getattr(tool_catalog, "get_openai_schemas", None)
                refreshed_schemas = (
                    schema_getter() if schema_getter is not None else tool_schemas
                )
                if refreshed_schemas != tool_schemas:
                    tool_schemas[:] = refreshed_schemas
                    compactor.tool_schemas = list(refreshed_schemas)
                if ctx.extras.get("interaction_required"):
                    budget.stop_reason = "waiting"
                    break
                if budget.local_tool_recovery_exhausted_reason:
                    budget.stop_reason = budget.local_tool_recovery_exhausted_reason
                    ctx.extras["_terminal_outcome"] = "blocked"
                    explanation = (
                        "工具连续返回相同失败或没有产生新进展，本轮已停止并保留"
                        "已有结果。请检查连接、参数或缩小任务范围后重试。"
                    )
                    blocks.append({"type": "text", "text": explanation})
                    yield HarnessEvent.text(
                        explanation,
                        step=budget.steps,
                        elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                    )
                    break
                continue

            if assistant_content:
                from app.conversation.engine import check_turn_completion

                gate_passed, gate_reason = await asyncio.to_thread(
                    check_turn_completion,
                    ctx.turn_id,
                    tool_catalog.user_pk,
                    tuple(ctx.extras.get("attachment_execution_requirements") or ()),
                )
                if not gate_passed:
                    # Keep the sampled candidate in the exact transcript—the
                    # stream already exposed its deltas—but do not mislabel it
                    # as successful completion. Give the model a bounded local
                    # opportunity to finish/revise authoritative runtime state.
                    blocks.append({"type": "text", "text": assistant_content})
                    messages.append({"role": "assistant", "content": assistant_content})
                    incomplete_candidate_attempts += 1
                    if incomplete_candidate_attempts >= _LOCAL_RECOVERY_ATTEMPTS:
                        budget.stop_reason = gate_reason or "completion_gate_blocked"
                        ctx.extras["_terminal_outcome"] = "blocked"
                        if str(gate_reason).startswith(
                            "attachment_visual_layout_unavailable:"
                        ):
                            explanation = (
                                "当前只取得了文本/OCR 投影，尚无真实页面视觉读取能力，"
                                "因此不能声称已经检查字体、颜色、排版或视觉布局。"
                            )
                        elif str(gate_reason).startswith(
                            "attachment_full_coverage_incomplete:"
                        ):
                            explanation = (
                                "本轮要求完整审阅，但仍有明确来源未完成全文分段读取；"
                                "已保留当前部分结果，未把抽样片段冒充完整覆盖。"
                            )
                        else:
                            explanation = (
                                "本轮未能安全标记为完成：仍有未闭合的工具调用。"
                                if gate_reason == "unresolved_tool_calls"
                                else "本轮已保留部分结果，但复杂任务计划仍有未完成阶段。"
                            )
                        blocks.append({"type": "text", "text": explanation})
                        yield HarnessEvent.text(
                            explanation,
                            step=budget.steps,
                            elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                        )
                        break
                    messages.append(
                        runtime_control_message(
                            "completion_gate",
                            (
                                "The completion candidate cannot be accepted yet: "
                                f"{gate_reason}. Continue the current task. If an "
                                "AgentTask exists, use task_update so every phase is "
                                "completed or explicitly skipped before the final "
                                "answer. Do not claim completion prematurely."
                            ),
                        )
                    )
                    pending_text_for_block = ""
                    continue

                # Final answer — terminator for the loop. NB:
                # ``reasoning_acc`` is intentionally NOT persisted on
                # this path. The thinking trace is intra-turn only —
                # it must round-trip while the loop is calling tools
                # within a single user-turn, but the persisted message
                # (``content_blocks_json``) carries only the visible
                # ``text`` blocks. On the NEXT user turn we start
                # fresh from system + persisted blocks; the model
                # generates new reasoning_content for that turn from
                # scratch. Discarding is correct.
                blocks.append({"type": "text", "text": assistant_content})
                yield HarnessEvent.text(
                    assistant_content,
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )
                break

            # Empty response → nudge for an explicit final answer.
            empty_response_attempts += 1
            if empty_response_attempts >= _LOCAL_RECOVERY_ATTEMPTS:
                budget.stop_reason = "empty_model_response"
                ctx.extras["_terminal_outcome"] = "blocked"
                explanation = "模型连续未给出可交付回答，本轮已停止并保留已有结果。"
                blocks.append({"type": "text", "text": explanation})
                yield HarnessEvent.text(
                    explanation,
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )
                break
            messages.append(
                runtime_control_message(
                    "empty_response_recovery",
                    "Please provide a final answer now based on gathered tool outputs.",
                )
            )

    # ── LLM streaming primitives ──────────────────────────────────

    async def _call_llm_stream(
        self,
        *,
        client: Any,
        profile: Any,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        compactor: ActiveTurnContextReducer,
        budget: AgentRunState,
        turn_id: str | None = None,
        user_pk: int = 0,
        dispatch_generation: int = 1,
        model_step: int = 0,
    ) -> tuple[Any, float]:
        attempt = 0
        current_call_id: str | None = None
        current_deadline: float | None = None

        async def _make_call() -> Any:
            nonlocal attempt, current_call_id, current_deadline
            attempt += 1
            await compactor.revalidate_memory(messages, user_pk=user_pk)
            request = build_provider_request(
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
                temperature=settings.AGENT_TEMPERATURE,
                max_tokens=min(
                    settings.AGENT_MAX_RESPONSE_TOKENS,
                    int(getattr(profile, "max_output_tokens", 0) or 0)
                    or settings.AGENT_MAX_RESPONSE_TOKENS,
                ),
            )
            current_call_id = (
                f"model:{dispatch_generation}:{model_step}:{attempt}"
                if turn_id and user_pk > 0
                else None
            )
            if current_call_id:
                await asyncio.to_thread(
                    start_model_dispatch_for_turn,
                    call_id=current_call_id,
                    turn_id=turn_id,
                    user_id=user_pk,
                    dispatch_generation=dispatch_generation,
                    provider=str(getattr(profile, "provider", "unknown") or "unknown"),
                    model=str(getattr(profile, "model", "unknown") or "unknown"),
                    fingerprint=request_fingerprint(
                        messages=request.messages,
                        tools=request.tools,
                        system=request.system,
                        max_tokens=request.max_tokens,
                        temperature=request.temperature,
                    ),
                    token_allowance=usage_runtime.llm_allowance(
                        {
                            "system": request.system,
                            "messages": request.messages,
                            "tools": request.tools,
                        },
                        request.max_tokens,
                    )[1],
                    usage_units=usage_runtime.llm_allowance(
                        {
                            "system": request.system,
                            "messages": request.messages,
                            "tools": request.tools,
                        },
                        request.max_tokens,
                    )[0],
                )
                request = replace(
                    request,
                    usage_permit=reservation_id(user_pk, turn_id, current_call_id),
                )
            current_deadline = (
                asyncio.get_running_loop().time()
                + settings.MODEL_STREAM_DEADLINE_SECONDS
            )
            try:
                return await asyncio.wait_for(
                    ModelProviderAdapter(
                        client=client,
                        profile=profile,
                    ).start_stream(request),
                    settings.MODEL_STREAM_DEADLINE_SECONDS,
                )
            except BaseException as exc:
                if current_call_id:
                    await asyncio.to_thread(
                        finish_model_dispatch,
                        turn_id=turn_id,
                        call_id=current_call_id,
                        dispatch_generation=dispatch_generation,
                        status=dispatch_failure_status(exc),
                        error_code=type(exc).__name__,
                    )
                if dispatch_failure_status(exc) == "unknown" and not isinstance(
                    exc, asyncio.CancelledError
                ):
                    raise ModelOutcomeUnknownError("model_outcome_unknown") from exc
                raise

        async def _on_context_too_long() -> bool:
            messages[:], should_retry = await compactor.on_context_too_long(messages)
            # The retry stays inside this model step; it never consumed a new
            # loop step to refund. Rewinding would reuse a durable call identity
            # when the next tool-result-driven iteration starts.
            return should_retry

        started = time.perf_counter()
        stream = await call_with_retry(
            _make_call,
            max_retries=3,
            on_context_too_long=_on_context_too_long,
        )
        tracked = durable_model_stream(
            stream,
            turn_id=turn_id,
            call_id=current_call_id,
            dispatch_generation=dispatch_generation,
            deadline=current_deadline,
        )
        return tracked, round((time.perf_counter() - started) * 1000, 2)

    async def _consume_stream(
        self,
        stream: Any,
        budget: AgentRunState,
        tool_calls_acc: list[_ToolCallAccumulator],
        reasoning_acc: list[str],
        *,
        compactor: ActiveTurnContextReducer | None = None,
        request_messages: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[HarnessEvent | str, None]:
        """Yield either a HarnessEvent (text_delta) for SSE OR a raw
        text-chunk str for the loop to accumulate.

        ``reasoning_acc`` is a mutable single-element-style list the
        caller passes in to capture the model's ``reasoning_content``
        (DeepSeek / o1-style thinking-mode field). Same pattern as
        ``tool_calls_acc``: out-of-band side-channel because the yield
        protocol is already overloaded with two types. We do NOT yield
        reasoning as ``text_delta`` — it's the model's internal scratch
        pad and the frontend doesn't render it; we only need it to
        replay back into the NEXT LLM call (the API errors out
        otherwise — see issue C in commit message).
        """
        from app.agent_runtime.tool_call_streaming import ToolCallAssembler

        assembler = ToolCallAssembler()
        async for chunk in stream:
            event = (
                chunk
                if isinstance(chunk, ProviderStreamEvent)
                else normalize_openai_chunk(chunk)
            )
            assembler.feed(event)
            if event.usage is not None:
                usage = event.usage
                budget.prompt_tokens += usage.prompt_tokens
                budget.completion_tokens += usage.completion_tokens
                budget.cache_read_tokens += usage.cache_read_tokens
                budget.cache_creation_tokens += usage.cache_creation_tokens
                if compactor is not None and request_messages is not None:
                    compactor.observe_provider_prompt_tokens(
                        usage.prompt_tokens,
                        request_messages,
                    )

            # Thinking-mode reasoning trace. DeepSeek V3.x / V4 Flash
            # and OpenAI o1-mini stream this on a separate ``delta``
            # field. The downstream API REQUIRES us to send it back
            # on the next-turn assistant message — without it the
            # second LLM call rejects with HTTP 400 "The
            # reasoning_content in the thinking mode must be passed
            # back to the API". So we accumulate even though we never
            # surface it to the UI.
            if event.reasoning_delta:
                reasoning_acc.append(event.reasoning_delta)

            if event.text_delta:
                # Always accumulate into the loop's local text buffer.
                yield event.text_delta
                # live == replay (AGT-5): this text lands in the persisted
                # blocks, so it MUST also stream — the old saw_tool_call
                # gate made replay show text the live viewer never saw.
                yield HarnessEvent.text_delta(
                    event.text_delta,
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )

        tool_calls_acc.extend(assembler.finish())

    # ── Tool execution ────────────────────────────────────────────


__all__ = ["AgentLoopStrategy"]
