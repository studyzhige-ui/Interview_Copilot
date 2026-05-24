"""L2 ReAct agent strategy — the autonomous tool-calling loop.

Hosts the ``while True:`` agent loop that used to live in
``agent_runtime.query_engine.QueryEngine._query_loop``. Everything that
was multi-turn outer-shell concern (memory recall, context assembly,
transcript persistence, post-turn maintenance) is now in
:class:`~app.conversation.engine.ConversationEngine`; this strategy
only handles the per-turn execution.

The strategy:
  * builds the initial messages array from the prepared context
  * drives the LLM↔tool ReAct loop until a final answer / budget stop
  * tracks token usage + budget on its own (engine reads back via
    :class:`StrategyResult`)
  * emits ``HarnessEvent`` for SSE
  * builds the Anthropic-style ``content_blocks_json`` chain
    (interleaved text/tool_use/tool_result) so the engine can persist
    it for the Claude-Code-style folded-card frontend UX
  * writes ``agent_runs`` + ``agent_steps`` trace inline (developer
    debugging surface, distinct from the user-facing transcript)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator

from app.agent_runtime.agent_progress_hooks import PostSamplingHookRunner
from app.agent_runtime.context_compactor import QueryLoopCompactor
from app.agent_runtime.react_agent import (
    AgentBudget,
    _args_summary,
    _result_summary,
    _tool_call_payload,
)
from app.agent_runtime.retry_utils import call_with_retry
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
from app.conversation.events import HarnessEvent
from app.conversation.strategy import StrategyContext, StrategyResult
from app.core.config import settings
from app.core.model_registry import build_async_openai_client_for_role
from app.services.agent_trace_service import append_step, create_run, finish_run

# Trigger tool self-registration on first import.
import app.agent_runtime.tools  # noqa: F401

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是 Interview Copilot 的执行 Agent。你的职责是帮助用户完成面试准备的复杂任务。

你了解用户的背景（简历、面试历史、记忆），能够：
- 分析岗位要求（JD）与用户能力的差距
- 基于面试历史识别薄弱环节并制定学习计划
- 搜索互联网获取面经、公司信息、技术资料
- 从知识库检索八股文和技术文档
- 将重要发现存入用户记忆供未来参考
- 导出结构化的分析报告和学习笔记为文件

规则：
- 先了解用户当前状态（简历、面试历史），再给建议
- 使用工具获取真实数据，不要编造
- 输出结构化的、可执行的建议
- 如果信息不足，明确告诉用户缺什么
- 将重要结论和发现用 save_memory 存储
"""


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
        # ── Per-turn state ────────────────────────────────────────
        budget = AgentBudget(started_at=time.perf_counter())
        client, profile = build_async_openai_client_for_role("agent")
        compactor = QueryLoopCompactor(profile=profile)
        tool_schemas = registry.get_openai_schemas()

        # Persistent trace surface (developer view) lives in agent_runs/
        # agent_steps. The user-facing transcript with content_blocks
        # is built up in ``blocks`` below and handed back via
        # ``result.assistant_blocks`` for the engine to persist.
        run_id = await create_run(
            user_id=ctx.user_id, session_id=ctx.session_id,
            goal=ctx.user_message, mode="function_calling",
        )
        ctx.run_id = run_id

        post_sampling_hooks = PostSamplingHookRunner(
            run_id=run_id,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
        )

        # Render the full AssembledContext so the agent sees memory +
        # debrief reference + RAG chunks + session state + recent
        # turns. The system_rules slot is suppressed here — the agent
        # has its own SYSTEM_PROMPT loaded as a separate message —
        # but every other SLOT_ORDER slot reaches the LLM.
        from app.services.chat.context_assembly_pipeline import prompt_renderer
        grounding_text = (
            prompt_renderer.render_answer_prompt(ctx.assembled, system_rules="")
            if ctx.assembled is not None else "No context."
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": (
                f"Available tools:\n{registry.format_manifest()}\n\n"
                f"Conversation context:\n{grounding_text or 'No context.'}"
            )},
            {"role": "user", "content": ctx.user_message},
        ]

        # Accumulated Anthropic-style content blocks for the final
        # assistant turn. Built up as the loop encounters text / tool
        # calls / tool results so the persisted message faithfully
        # replays the same UX the frontend showed live.
        blocks: list[dict[str, Any]] = []

        # Trace blob mirrored to agent_steps for the developer view.
        trace: list[dict[str, Any]] = []

        status = "completed"
        error_message: str | None = None
        final_answer = ""

        try:
            async for event in self._loop(
                ctx=ctx,
                messages=messages,
                blocks=blocks,
                trace=trace,
                budget=budget,
                client=client,
                profile=profile,
                compactor=compactor,
                tool_schemas=tool_schemas,
                post_sampling_hooks=post_sampling_hooks,
                run_id=run_id,
            ):
                if event.type.value == "text":
                    final_answer = event.data.get("content", "")
                yield event
        except Exception as exc:
            status = "failed"
            error_message = str(exc)
            final_answer = "Agent 执行失败，请稍后重试。"
            logger.error("AgentLoopStrategy crashed: %s", exc)
            await append_step(
                run_id=run_id, step_index=budget.steps + 1,
                action_type="error", observation={"error": str(exc)},
                assistant_content="", is_error=True, latency_ms=0.0,
            )
        finally:
            # Always persist agent_runs row (developer view) even on
            # failure — separate from the user-facing chat transcript
            # which the ConversationEngine handles uniformly.
            await finish_run(
                run_id=run_id, status=status,
                final_answer=final_answer,
                steps_used=budget.steps,
                tool_calls=budget.tool_calls,
                prompt_tokens=budget.prompt_tokens,
                completion_tokens=budget.completion_tokens,
                total_latency_ms=round(budget.elapsed_seconds * 1000, 2),
                error_message=error_message,
                budget_stop_reason=budget.stop_reason,
            )

        # Ensure a trailing text block exists (so the persisted message
        # always carries a final answer, even when the loop ended on
        # budget stop).
        if not final_answer:
            final_answer = (
                f"Agent 执行因预算策略停止: {budget.stop_reason}. "
                "请缩小目标范围后重试。"
                if budget.stop_reason else "Agent 无法生成最终回答。"
            )
            blocks.append({"type": "text", "text": final_answer})
        elif not blocks or blocks[-1].get("type") != "text":
            blocks.append({"type": "text", "text": final_answer})

        result.final_answer = final_answer
        result.assistant_blocks = blocks
        result.prompt_tokens = budget.prompt_tokens
        result.completion_tokens = budget.completion_tokens
        result.tool_calls = budget.tool_calls
        result.steps_used = budget.steps
        result.stop_reason = budget.stop_reason
        # Surface run_id so callers of the batch API (run_react_agent)
        # can plumb it back to the UI for trace lookups. Engine
        # passes ``ctx`` through to the strategy untouched, so this
        # mutation is safe.
        result.extras["run_id"] = run_id

        # Final budget event carries run_id so the batch wrapper
        # (run_react_agent) can plumb it back to the API response —
        # the streaming wire format doesn't have a dedicated channel
        # for one-shot identifiers and adding a new HarnessEvent type
        # would break existing frontend dispatchers. The frontend
        # already ignores fields it doesn't recognise on budget.
        budget_payload = budget.to_dict()
        budget_payload["run_id"] = run_id
        yield HarnessEvent.budget(
            budget_payload,
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
        trace: list[dict[str, Any]],
        budget: AgentBudget,
        client: Any,
        profile: Any,
        compactor: QueryLoopCompactor,
        tool_schemas: list[dict[str, Any]],
        post_sampling_hooks: PostSamplingHookRunner,
        run_id: str,
    ) -> AsyncGenerator[HarnessEvent, None]:
        # Track which text we've already emitted as a block so the
        # final pass doesn't double-count.
        pending_text_for_block = ""

        while True:
            # Budget check
            stop = budget.check()
            if stop:
                budget.stop_reason = stop
                await append_step(
                    run_id=run_id, step_index=budget.steps + 1,
                    action_type="budget_stop",
                    observation={"error": stop},
                    assistant_content="", is_error=True, latency_ms=0.0,
                )
                break

            budget.consume_step()

            # Layer 1 + 2 of the compactor (pre-LLM pruning + token warning)
            messages[:] = compactor.pre_llm_compact(messages, budget.prompt_tokens)
            if compactor.is_at_blocking_limit(budget.prompt_tokens):
                budget.stop_reason = "context_window_exhausted"
                await append_step(
                    run_id=run_id, step_index=budget.steps,
                    action_type="budget_stop",
                    observation={"error": "context_window_exhausted"},
                    assistant_content="", is_error=True, latency_ms=0.0,
                )
                yield HarnessEvent.error(
                    "上下文窗口即将耗尽，停止执行。请缩小目标范围后重试。",
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )
                break

            stream, _ = await self._call_llm_stream(
                client=client, profile=profile, messages=messages,
                tool_schemas=tool_schemas, compactor=compactor, budget=budget,
            )

            assistant_content = ""
            tool_calls_acc: list[_ToolCallAccumulator] = []
            stream_started_at = time.perf_counter()

            async for ev in self._consume_stream(stream, budget, tool_calls_acc):
                if isinstance(ev, HarnessEvent):
                    yield ev
                elif isinstance(ev, str):
                    assistant_content += ev

            latency_ms = round((time.perf_counter() - stream_started_at) * 1000, 2)
            compactor.reset_circuit_breaker()

            # If the model emitted any text in this turn (whether it
            # ends in tool_calls or final answer), capture it as a
            # block before any tool blocks are appended. This keeps
            # the storyline order: text → tools → text → tools → text.
            if assistant_content:
                pending_text_for_block += assistant_content
                if tool_calls_acc:
                    blocks.append({
                        "type": "text", "text": pending_text_for_block.strip(),
                    })
                    pending_text_for_block = ""

            if tool_calls_acc:
                async for ev in self._execute_tools(
                    ctx=ctx, messages=messages, blocks=blocks,
                    trace=trace, tool_calls_acc=tool_calls_acc,
                    assistant_content=assistant_content,
                    budget=budget, post_sampling_hooks=post_sampling_hooks,
                    run_id=run_id,
                ):
                    yield ev
                continue

            if assistant_content:
                # Final answer — terminator for the loop.
                trace.append({
                    "step": budget.steps, "tool": None, "args": {},
                    "observation": {}, "latency_ms": latency_ms,
                    "is_error": False,
                })
                await append_step(
                    run_id=run_id, step_index=budget.steps,
                    action_type="final_answer",
                    assistant_content=assistant_content,
                    observation={}, is_error=False, latency_ms=latency_ms,
                )
                blocks.append({"type": "text", "text": assistant_content})
                yield HarnessEvent.text(
                    assistant_content, step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                )
                break

            # Empty response → nudge for an explicit final answer.
            messages.append({
                "role": "user",
                "content": "Please provide a final answer now based on gathered tool outputs.",
            })

    # ── LLM streaming primitives ──────────────────────────────────

    async def _call_llm_stream(
        self,
        *,
        client: Any,
        profile: Any,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        compactor: QueryLoopCompactor,
        budget: AgentBudget,
    ) -> tuple[Any, float]:
        async def _make_call() -> Any:
            return await client.chat.completions.create(
                model=profile.model,
                messages=messages,
                tools=tool_schemas if tool_schemas else None,
                tool_choice="auto" if tool_schemas else None,
                temperature=settings.AGENT_TEMPERATURE,
                max_tokens=settings.AGENT_MAX_RESPONSE_TOKENS,
                stream=True,
                stream_options={"include_usage": True},
            )

        async def _on_context_too_long() -> bool:
            messages[:], should_retry = compactor.on_context_too_long(messages)
            if should_retry:
                budget.refund_step()
            return should_retry

        started = time.perf_counter()
        stream = await call_with_retry(
            _make_call, max_retries=3,
            on_context_too_long=_on_context_too_long,
        )
        return stream, round((time.perf_counter() - started) * 1000, 2)

    async def _consume_stream(
        self,
        stream: Any,
        budget: AgentBudget,
        tool_calls_acc: list[_ToolCallAccumulator],
    ) -> AsyncGenerator[HarnessEvent | str, None]:
        """Yield either a HarnessEvent (text_delta) for SSE OR a raw
        text-chunk str for the loop to accumulate."""
        index_map: dict[int, _ToolCallAccumulator] = {}
        saw_tool_call = False

        async for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage = chunk.usage
                budget.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                budget.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                # Always accumulate into the loop's local text buffer.
                yield delta.content
                if not saw_tool_call:
                    yield HarnessEvent.text_delta(
                        delta.content, step=budget.steps,
                        elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                    )

            if delta.tool_calls:
                saw_tool_call = True
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in index_map:
                        acc = _ToolCallAccumulator(
                            id=tc_delta.id or "",
                            name=(tc_delta.function.name
                                  if tc_delta.function and tc_delta.function.name else ""),
                            arguments="",
                        )
                        index_map[idx] = acc
                        tool_calls_acc.append(acc)
                    else:
                        acc = index_map[idx]
                    if tc_delta.id:
                        acc.id = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            acc.name = tc_delta.function.name
                        if tc_delta.function.arguments:
                            acc.arguments += tc_delta.function.arguments

    # ── Tool execution ────────────────────────────────────────────

    async def _execute_tools(
        self,
        *,
        ctx: StrategyContext,
        messages: list[dict[str, Any]],
        blocks: list[dict[str, Any]],
        trace: list[dict[str, Any]],
        tool_calls_acc: list[_ToolCallAccumulator],
        assistant_content: str,
        budget: AgentBudget,
        post_sampling_hooks: PostSamplingHookRunner,
        run_id: str,
    ) -> AsyncGenerator[HarnessEvent, None]:
        messages.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": [_tool_call_payload(c) for c in tool_calls_acc],
        })

        turn_tool_messages: list[dict[str, Any]] = []

        for tc in tool_calls_acc:
            tool_name = tc.name
            tool_error = False
            tool_started = time.perf_counter()

            # Capture the tool_use BLOCK before invoking — so the UI
            # can show a "running" folded card even mid-flight (in the
            # future when streaming tool persistence lands).
            try:
                parsed_args = parse_tool_arguments(tc.arguments)
            except Exception:
                parsed_args = {}
            tool_use_block = {
                "type": "tool_use",
                "id": tc.id,
                "name": tool_name,
                "input": parsed_args,
            }

            yield HarnessEvent.tool_start(
                tool_name, _args_summary(tc.arguments),
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
            )

            observation: dict[str, Any]
            if budget.tool_usage[tool_name] >= settings.AGENT_MAX_CALLS_PER_TOOL:
                observation = {"error": "tool_call_limit_exceeded", "tool_name": tool_name}
                tool_error = True
            elif tool_name not in registry:
                observation = {"error": "unknown_tool", "tool_name": tool_name}
                tool_error = True
            else:
                try:
                    tool_ctx = AgentToolContext(
                        user_id=ctx.user_id, session_id=ctx.session_id,
                    )
                    observation = await asyncio.wait_for(
                        registry.dispatch(tool_name, parsed_args, tool_ctx),
                        timeout=settings.AGENT_TOOL_TIMEOUT_SECONDS,
                    )
                    if "error" in observation:
                        tool_error = True
                except asyncio.TimeoutError:
                    observation = {"error": "tool_timeout", "tool_name": tool_name}
                    tool_error = True
                except ValueError as exc:
                    observation = {"error": str(exc)}
                    tool_error = True
                except Exception as exc:  # noqa: BLE001
                    observation = {"error": "tool_execution_failed", "detail": str(exc)}
                    tool_error = True

            budget.consume_tool_call(tool_name)
            latency_ms = round((time.perf_counter() - tool_started) * 1000, 2)

            # Persist large tool results to disk; the LLM context only
            # keeps a small preview pointer.
            result_text = safe_json_dumps(observation)
            result_text = maybe_persist_result(
                content=result_text,
                tool_name=tool_name,
                tool_call_id=tc.id,
                session_id=ctx.session_id,
            )

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_text,
            }
            messages.append(tool_msg)
            turn_tool_messages.append(tool_msg)

            trace.append({
                "step": budget.steps, "tool": tool_name,
                "args": parsed_args if not tool_error else {},
                "observation": observation,
                "latency_ms": latency_ms, "is_error": tool_error,
            })

            # Persistent chain (frontend folded-card replay).
            # ``content`` carries the full LLM-visible result text,
            # which is either the raw JSON observation or a
            # ``<persisted-output ...>`` pointer string. The frontend
            # uses ``content`` to render the expanded view and
            # ``summary`` as the always-visible folded label.
            blocks.append(tool_use_block)
            blocks.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "is_error": tool_error,
                "latency_ms": latency_ms,
                "summary": _result_summary(observation),
                "content": result_text,
            })

            await append_step(
                run_id=run_id, step_index=budget.steps,
                action_type="tool_call", tool_name=tool_name,
                tool_call_id=tc.id,
                tool_args=parsed_args if not tool_error else {},
                observation=observation,
                assistant_content=assistant_content,
                is_error=tool_error, latency_ms=latency_ms,
            )

            yield HarnessEvent.tool_done(
                tool_name, _result_summary(observation),
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                tool_latency_ms=latency_ms, is_error=tool_error,
            )

        if turn_tool_messages:
            enforce_turn_budget(turn_tool_messages, ctx.session_id)

        if post_sampling_hooks:
            await post_sampling_hooks.execute(
                step=budget.steps,
                messages=messages,
                tool_results=turn_tool_messages,
                budget_snapshot=budget.to_dict(),
            )


__all__ = ["AgentLoopStrategy"]
