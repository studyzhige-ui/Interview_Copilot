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

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator


# Trigger tool self-registration on first import.
import app.agent_runtime.tools  # noqa: F401
from app.agent_runtime.context_compactor import QueryLoopCompactor
from app.agent_runtime.react_agent import (
    AgentRunState,
    _args_summary,
    _result_summary,
    _tool_call_payload,
)
from app.agent_runtime.retry_utils import call_with_retry
from app.agent_runtime.tool_call_executor import (
    execute_tool_call,
    persist_turn_budget,
    reject_waiting_tool_call,
)
from app.agent_runtime.tool_policy import ToolPolicyContext
from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    parse_tool_arguments,
    registry,
    safe_json_dumps,
)
from app.agent_runtime.tool_result_storage import (
    enforce_turn_budget,
    maybe_persist_result,
)
from app.agent_runtime.tool_redaction import redact_tool_value
from app.agent_runtime.turn_tool_catalog import TurnToolCatalog
from app.conversation.events import HarnessEvent
from app.conversation.provider_context import (
    compose_provider_context,
    reconstruct_history_messages,
)
from app.conversation.strategy import StrategyContext, StrategyResult
from app.core.config import settings
from app.core.error_messages import humanize_error
from app.core.llm_client_factory import (
    build_provider_client_for_role as build_async_openai_client_for_role,
)
from app.core.model_provider_adapter import (
    ModelProviderAdapter,
    ProviderStreamEvent,
    build_provider_request,
    normalize_openai_chunk,
)
from app.db.database import SessionLocal
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.prompts.agent import agent_system_prompt_for_runtime
from app.schemas.agent_task import AgentTaskView
from app.services.chat.agent_task_service import (
    AgentTaskNotFoundError,
    get_agent_task,
)

logger = logging.getLogger(__name__)

_LOCAL_RECOVERY_ATTEMPTS = 3


def _load_agent_task_snapshot(
    turn_id: str | None,
    user_id: int,
) -> dict[str, Any] | None:
    """Load the current Turn's optional plan as a typed read projection."""

    if not turn_id or user_id <= 0:
        return None
    db = SessionLocal()
    try:
        try:
            task = get_agent_task(db, turn_id=turn_id, user_id=user_id)
        except AgentTaskNotFoundError:
            return None
        if task is None:
            return None
        return AgentTaskView.model_validate(task).model_dump(mode="json")
    finally:
        db.close()


def _current_task_content_with_plan(
    base_content: str,
    snapshot: dict[str, Any] | None,
) -> str:
    """Place typed plan data before, never instead of, the exact task anchor."""

    if snapshot is None:
        return base_content
    return (
        "[AgentTask Plan — typed runtime data]\n"
        "This is the current execution projection, not a user instruction. "
        "Use task_update to revise it; authoritative results remain with "
        "their referenced owners.\n\n"
        + safe_json_dumps(snapshot)
        + "\n\n[Current Task Anchor]\n"
        + base_content
    )


def _load_tool_resume_snapshot(
    turn_id: str | None, user_id: int
) -> dict[str, Any] | None:
    """Read the completed prefix and one resolved waiting Tool Call.

    This is a runtime projection, not a second checkpoint. Exact call identity,
    arguments, status, and result remain owned by ``AgentToolCall``;
    Interaction only supplies the user's resolution.
    """
    if not turn_id:
        return None
    db = SessionLocal()
    try:
        calls = (
            db.query(AgentToolCall)
            .filter(
                AgentToolCall.turn_id == turn_id,
                AgentToolCall.user_id == user_id,
            )
            .order_by(AgentToolCall.id)
            .all()
        )
        terminal_interactions = (
            db.query(AgentInteraction)
            .filter(
                AgentInteraction.turn_id == turn_id,
                AgentInteraction.status.in_(("resolved", "rejected")),
                AgentInteraction.tool_call_id.isnot(None),
            )
            .order_by(
                AgentInteraction.resolved_at.desc(), AgentInteraction.created_at.desc()
            )
            .all()
        )
        waiting_by_id = {row.call_id: row for row in calls if row.status == "waiting"}
        interaction = next(
            (row for row in terminal_interactions if row.tool_call_id in waiting_by_id),
            None,
        )
        if interaction is None:
            return None
        waiting = waiting_by_id[str(interaction.tool_call_id)]
        return {
            "prior": [
                {
                    "call_id": row.call_id,
                    "tool_name": row.tool_name,
                    "arguments": dict(row.arguments_json or {}),
                    "result": dict(row.result_json or {}),
                    "status": row.status,
                    "duration_ms": float(row.duration_ms or 0),
                }
                for row in calls
                if row.id < waiting.id and row.status != "running"
            ],
            "waiting": {
                "call_id": waiting.call_id,
                "tool_name": waiting.tool_name,
                "arguments": dict(waiting.arguments_json or {}),
            },
            "resolution_status": interaction.status,
            "interaction_kind": interaction.kind,
            "resolution": dict(interaction.resolution_json or {}),
        }
    finally:
        db.close()


def _append_replayed_tool(
    messages: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    call: dict[str, Any],
) -> None:
    call_id = str(call["call_id"])
    tool_name = str(call["tool_name"])
    arguments = dict(call.get("arguments") or {})
    result = dict(call.get("result") or {})
    result_text = safe_json_dumps(result)
    messages.extend(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": safe_json_dumps(arguments),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": call_id, "content": result_text},
        ]
    )
    blocks.extend(
        [
            {
                "type": "tool_use",
                "id": call_id,
                "name": tool_name,
                "input": arguments,
            },
            {
                "type": "tool_result",
                "tool_use_id": call_id,
                "is_error": bool(result.get("error")),
                "latency_ms": float(call.get("duration_ms") or 0),
                "summary": _result_summary(result),
                "content": result_text,
            },
        ]
    )


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


# Repeated identical tool calls (same tool + same args) are steered with a soft
# nudge at these counts, never a hard stop. Replaces the old per-tool hard cap;
# termination remains semantic except for context exhaustion or cancellation.
_REPEAT_NUDGE_SOFT = 3
_REPEAT_NUDGE_FIRM = 6


def _repeat_call_nudge(tool_name: str, count: int) -> str:
    """Soft-steer message when a tool is re-called with identical arguments."""
    base = (
        f"Note: `{tool_name}` has now been called {count} times with identical "
        f"arguments — repeating it rarely yields new information."
    )
    if count >= _REPEAT_NUDGE_FIRM:
        return (
            base + " Stop repeating it: change the arguments, try a different "
            "tool, or give your final answer based on what you already have."
        )
    return (
        base + " Consider changing the arguments, trying a different tool, or "
        "answering with what you have."
    )


def _reconstruct_history_messages(turns: list[dict]) -> list[dict[str, Any]]:
    """Compatibility seam backed by the shared provider context projection."""

    return reconstruct_history_messages(turns)


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
        if ctx.assembled is not None and ctx.assembled.sources:
            yield HarnessEvent.sources(ctx.assembled.sources, step=0, elapsed_ms=0)

        # ── Per-turn state ────────────────────────────────────────
        budget = AgentRunState(started_at=time.perf_counter())
        # Local compatibility name is retained for focused tests; the factory
        # now returns the selected provider's native transport client.
        client, profile = build_async_openai_client_for_role(
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
        )
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
        from app.services.chat.context_assembly_pipeline import prompt_renderer

        runtime_prompt = agent_system_prompt_for_runtime(ctx.runtime_profile)
        agent_system_prompt = f"{runtime_prompt}\n\n{tool_catalog.format_prompt()}"
        tool_schemas = tool_catalog.get_openai_schemas()
        history_messages: list[dict[str, Any]] = []
        task_snapshot = await asyncio.to_thread(
            _load_agent_task_snapshot,
            ctx.turn_id,
            tool_catalog.user_pk,
        )
        if ctx.assembled is not None:
            # Only stable rules stay in the system prefix. The lossy summary
            # is the first chronological data message; prior exact turns
            # follow it, and per-turn product/RAG data stays beside the current
            # user input.
            projection = compose_provider_context(
                ctx.assembled,
                renderer=prompt_renderer,
                system_prompt=agent_system_prompt,
            )
            system_block = projection.system
            history_messages.extend(projection.messages[:-1])
            current_task_content = str(projection.messages[-1]["content"])
        else:
            system_block = agent_system_prompt
            current_task_content = ctx.user_message
        base_current_task_content = current_task_content
        current_task_message: dict[str, Any] = {
            "role": "user",
            "content": _current_task_content_with_plan(
                base_current_task_content,
                task_snapshot,
            ),
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_block},
            *history_messages,
            current_task_message,
        ]
        compactor = QueryLoopCompactor(
            profile=profile,
            user_id=ctx.user_id,
            task_anchor=current_task_message,
            tool_schemas=tool_schemas,
        )

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
        if resume is not None:
            for prior_call in resume["prior"]:
                _append_replayed_tool(messages, blocks, prior_call)
                budget.tool_call_ids.add(str(prior_call["call_id"]))
            waiting_call = dict(resume["waiting"])
            waiting_id = str(waiting_call["call_id"])
            if resume["resolution_status"] == "rejected":
                rejected = await asyncio.to_thread(
                    reject_waiting_tool_call,
                    call_id=waiting_id,
                    turn_id=str(ctx.turn_id),
                    dispatch_generation=ctx.dispatch_generation,
                    reason=str(
                        (resume.get("resolution") or {}).get("reason", "user_rejected")
                    ),
                )
                _append_replayed_tool(
                    messages,
                    blocks,
                    {**waiting_call, "result": rejected, "status": "denied"},
                )
                budget.tool_call_ids.add(waiting_id)
            else:
                # Connection/readiness resolution only proves that prerequisite;
                # it never doubles as approval for the concrete effect.
                if resume.get("interaction_kind") == "approval":
                    ctx.extras["confirmed_tool_call_id"] = waiting_id
                ctx.extras["resume_tool_call_id"] = waiting_id
                resume_acc = _ToolCallAccumulator(
                    id=waiting_id,
                    name=str(waiting_call["tool_name"]),
                    arguments=safe_json_dumps(waiting_call.get("arguments") or {}),
                )
                async for event in self._execute_tools(
                    ctx=ctx,
                    messages=messages,
                    blocks=blocks,
                    tool_calls_acc=[resume_acc],
                    assistant_content="",
                    reasoning_content="",
                    budget=budget,
                    tool_catalog=tool_catalog,
                ):
                    yield event

        final_answer = ""
        ctx.extras.pop("_terminal_outcome", None)

        try:
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
        elif not blocks or blocks[-1].get("type") != "text":
            blocks.append({"type": "text", "text": final_answer})

        result.final_answer = final_answer
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
        compactor: QueryLoopCompactor,
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
                task_anchor["content"] = _current_task_content_with_plan(
                    base_task_content,
                    task_snapshot,
                )

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
                async for ev in self._execute_tools(
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
                        {
                            "role": "user",
                            "content": (
                                "The completion candidate cannot be accepted yet: "
                                f"{gate_reason}. Continue the current task. If an "
                                "AgentTask exists, use task_update so every phase is "
                                "completed or explicitly skipped before the final "
                                "answer. Do not claim completion prematurely."
                            ),
                        }
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
                {
                    "role": "user",
                    "content": "Please provide a final answer now based on gathered tool outputs.",
                }
            )

    # ── LLM streaming primitives ──────────────────────────────────

    async def _call_llm_stream(
        self,
        *,
        client: Any,
        profile: Any,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        compactor: QueryLoopCompactor,
        budget: AgentRunState,
    ) -> tuple[Any, float]:
        async def _make_call() -> Any:
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
            return await ModelProviderAdapter(
                client=client,
                profile=profile,
            ).start_stream(request)

        async def _on_context_too_long() -> bool:
            messages[:], should_retry = await compactor.on_context_too_long(messages)
            if should_retry:
                budget.refund_step()
            return should_retry

        started = time.perf_counter()
        stream = await call_with_retry(
            _make_call,
            max_retries=3,
            on_context_too_long=_on_context_too_long,
        )
        return stream, round((time.perf_counter() - started) * 1000, 2)

    async def _consume_stream(
        self,
        stream: Any,
        budget: AgentRunState,
        tool_calls_acc: list[_ToolCallAccumulator],
        reasoning_acc: list[str],
        *,
        compactor: QueryLoopCompactor | None = None,
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
        index_map: dict[int, _ToolCallAccumulator] = {}
        async for chunk in stream:
            event = (
                chunk
                if isinstance(chunk, ProviderStreamEvent)
                else normalize_openai_chunk(chunk)
            )
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

            if event.tool_call_deltas:
                for tc_delta in event.tool_call_deltas:
                    idx = tc_delta.index
                    if idx not in index_map:
                        acc = _ToolCallAccumulator(
                            id=tc_delta.call_id,
                            name=tc_delta.name,
                            arguments="",
                        )
                        index_map[idx] = acc
                        tool_calls_acc.append(acc)
                    else:
                        acc = index_map[idx]
                    if tc_delta.call_id:
                        acc.id = tc_delta.call_id
                    if tc_delta.name:
                        acc.name = tc_delta.name
                    if tc_delta.arguments_delta:
                        acc.arguments += tc_delta.arguments_delta

    # ── Tool execution ────────────────────────────────────────────

    async def _execute_tools(
        self,
        *,
        ctx: StrategyContext,
        messages: list[dict[str, Any]],
        blocks: list[dict[str, Any]],
        tool_calls_acc: list[_ToolCallAccumulator],
        assistant_content: str,
        reasoning_content: str,
        budget: AgentRunState,
        tool_catalog: TurnToolCatalog | None = None,
    ) -> AsyncGenerator[HarnessEvent, None]:
        # ``reasoning_content`` (thinking-mode trace) MUST round-trip
        # back to the API on the next assistant message — otherwise
        # DeepSeek V4 Flash / o1-style models reject the next call with
        # HTTP 400 "The reasoning_content in the thinking mode must be
        # passed back to the API". We attach it conditionally so plain
        # (non-thinking) models that never produce reasoning_content
        # don't get a confusing empty field.
        for tool_call in tool_calls_acc:
            if not tool_call.id or tool_call.id in budget.tool_call_ids:
                tool_call.id = f"call_{uuid.uuid4().hex}"
            budget.tool_call_ids.add(tool_call.id)

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [_tool_call_payload(c) for c in tool_calls_acc],
        }
        if reasoning_content:
            assistant_msg["reasoning_content"] = reasoning_content
        messages.append(assistant_msg)

        turn_tool_messages: list[dict[str, Any]] = []
        nudge_repeat = 0
        nudge_tool = ""
        replan_message = ""
        dispatcher = tool_catalog or registry

        async def run_tool(
            tc: _ToolCallAccumulator,
            parsed_args: dict[str, Any],
            tool_started: float,
        ) -> tuple[dict[str, Any], str, float]:
            tool_name = tc.name
            tool_ctx = AgentToolContext(
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
                user_pk=(tool_catalog.user_pk if tool_catalog else None),
                tool_call_id=tc.id,
            )
            policy_traits = getattr(dispatcher, "policy_traits", None)
            task_authorized, reversible = (
                policy_traits(tool_name, parsed_args, tool_ctx, ctx.user_message)
                if policy_traits is not None
                else (False, False)
            )

            async def dispatch() -> dict[str, Any]:
                if tool_name not in dispatcher:
                    return {"error": "unknown_tool", "tool_name": tool_name}
                return await dispatcher.dispatch(tool_name, parsed_args, tool_ctx)

            observation = await execute_tool_call(
                call_id=tc.id,
                turn_id=ctx.turn_id,
                session_id=ctx.session_id,
                user_id=tool_catalog.user_pk if tool_catalog else 0,
                tool_name=tool_name,
                arguments=parsed_args,
                timeout_seconds=settings.AGENT_TOOL_TIMEOUT_SECONDS,
                dispatch=dispatch,
                effect=dispatcher.effect_for(tool_name),
                policy_context=ToolPolicyContext(
                    execution_mode=str(ctx.extras.get("execution_mode", "standard")),
                    current_task_authorizes=task_authorized,
                    user_confirmed_this_call=bool(
                        ctx.extras.get("confirmed_tool_call_id") == tc.id
                    ),
                    reversible=reversible,
                ),
                dispatch_generation=ctx.dispatch_generation,
                resume_waiting=bool(ctx.extras.get("resume_tool_call_id") == tc.id),
            )
            latency_ms = round((time.perf_counter() - tool_started) * 1000, 2)
            # Persist large tool results to disk; the LLM context only
            # keeps a small preview pointer. maybe_persist_result does
            # sync file_path.write_text() for oversized content — offload
            # so a chatty agent step doesn't stall the loop on disk I/O.
            result_text = safe_json_dumps(observation)
            result_text = await asyncio.to_thread(
                maybe_persist_result,
                content=result_text,
                tool_name=tool_name,
                tool_call_id=tc.id,
                session_id=ctx.session_id,
            )
            return observation, result_text, latency_ms

        def concurrency_safe(name: str) -> bool:
            checker = getattr(dispatcher, "is_concurrency_safe", None)
            return bool(checker and checker(name))

        call_index = 0
        while call_index < len(tool_calls_acc):
            # Partition into consecutive safe batches. A mutating/unknown call
            # forms a one-item batch and therefore runs exclusively between
            # all earlier and later work, preserving observable ordering.
            batch_end = call_index + 1
            if concurrency_safe(tool_calls_acc[call_index].name):
                while batch_end < len(tool_calls_acc) and concurrency_safe(
                    tool_calls_acc[batch_end].name
                ):
                    batch_end += 1
            batch_calls = tool_calls_acc[call_index:batch_end]
            prepared: list[
                tuple[_ToolCallAccumulator, dict[str, Any], dict[str, Any], float]
            ] = []

            for tc in batch_calls:
                try:
                    parsed_args = parse_tool_arguments(tc.arguments)
                except Exception:
                    parsed_args = {}
                tool_use_block = {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": redact_tool_value(parsed_args),
                }
                tool_started = time.perf_counter()
                prepared.append((tc, parsed_args, tool_use_block, tool_started))
                yield HarnessEvent.tool_start(
                    tc.name,
                    _args_summary(tc.arguments),
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                    tool_call_id=tc.id,
                    input=redact_tool_value(parsed_args),
                )

            completed = await asyncio.gather(
                *(
                    run_tool(tc, parsed_args, tool_started)
                    for tc, parsed_args, _tool_use_block, tool_started in prepared
                )
            )

            # Deterministic replay: even when execution overlaps, observations,
            # content blocks, and SSE completion events follow model call order.
            for (tc, parsed_args, tool_use_block, _started), (
                observation,
                result_text,
                latency_ms,
            ) in zip(prepared, completed):
                tool_name = tc.name
                tool_error = "error" in observation
                # Canonical typed arguments make whitespace/key-order variants
                # the same action for repeat and failure-loop detection.
                canonical_args = json.dumps(
                    parsed_args,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                signature = f"{tool_name}\x00{canonical_args}"
                repeat_count = budget.consume_tool_call(tool_name, signature)
                await persist_turn_budget(ctx.turn_id, budget.to_dict())
                if repeat_count in (_REPEAT_NUDGE_SOFT, _REPEAT_NUDGE_FIRM):
                    nudge_repeat, nudge_tool = repeat_count, tool_name

                logger.info(
                    "tool_metric | tool=%s latency_ms=%.1f is_error=%s result_chars=%d step=%d",
                    tool_name,
                    latency_ms,
                    tool_error,
                    len(safe_json_dumps(observation)),
                    budget.steps,
                )

                incident = budget.observe_tool_result(
                    tool_name,
                    signature,
                    result_text,
                    is_error=tool_error,
                )
                if incident:
                    replan_message = incident
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                }
                messages.append(tool_msg)
                turn_tool_messages.append(tool_msg)

                # Persistent chain (frontend folded-card replay).
                # ``content`` carries the full LLM-visible result text,
                # which is either the raw JSON observation or a
                # ``<persisted-output ...>`` pointer string. The frontend
                # uses ``content`` to render the expanded view and
                # ``summary`` as the always-visible folded label.
                blocks.append(tool_use_block)
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "is_error": tool_error,
                        "latency_ms": latency_ms,
                        "summary": _result_summary(observation),
                        "content": result_text,
                    }
                )

                yield HarnessEvent.tool_done(
                    tool_name,
                    _result_summary(observation),
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                    tool_latency_ms=latency_ms,
                    is_error=tool_error,
                    # Ship the full result text on the wire so the live
                    # tool card can render the expanded view without a
                    # refresh. ``result_text`` is already capped at the
                    # per-tool ``max_result_chars`` ceiling so this won't
                    # blow up an SSE frame.
                    result_content=result_text,
                    # Mirror tool_start's id so the frontend can pair the
                    # tool_use / tool_result blocks by id rather than the
                    # ambient FIFO order — robust to parallel tools and
                    # makes the live-stream shape match the persisted
                    # blocks loaded by ``/chat/transcript``.
                    tool_call_id=tc.id,
                )

                if observation.get("error") in {
                    "interaction_required",
                    "connection_required",
                    "policy_required",
                }:
                    # The durable Interaction row is created at the Tool
                    # execution boundary. Stop before another model call; the
                    # worker will release this same Turn as ``waiting``.
                    ctx.extras["interaction_required"] = {
                        "tool_call_id": tc.id,
                        "kind": observation.get("interaction_type", "approval"),
                    }
                    interaction = observation.get("interaction")
                    if isinstance(interaction, dict):
                        yield HarnessEvent.interaction(
                            interaction,
                            step=budget.steps,
                            elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                        )

            call_index = batch_end
            if ctx.extras.get("interaction_required"):
                break

        if turn_tool_messages:
            enforce_turn_budget(turn_tool_messages, ctx.session_id)

        # Repeated identical tool calls: steer the model with a soft nudge
        # appended AFTER the tool results (never a hard stop). Placed after the
        # results so the
        # assistant(tool_calls)→tool→tool pairing stays intact.
        if nudge_repeat:
            messages.append(
                {
                    "role": "user",
                    "content": _repeat_call_nudge(nudge_tool, nudge_repeat),
                }
            )
        if replan_message:
            messages.append(
                {
                    "role": "user",
                    "content": replan_message
                    + " Revise the approach before continuing.",
                }
            )


__all__ = ["AgentLoopStrategy"]
