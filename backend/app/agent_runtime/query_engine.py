"""QueryEngine — orchestration layer for a single agent turn.

Extracts the monolithic ``run_react_agent_stream()`` into a class with
clearly separated lifecycle phases:

  _prepare_context()  → assemble messages[], hook runners, budget
  _query_loop()       → LLM call + tool execution loop (yields events)
  _finalize()         → trace persistence + stop hooks (Phase E)

Design references:
  Claude Code QueryEngine (query.ts):
    submitMessage() → single turn orchestrator
    _prepareContext() → context assembly
    _queryLoop() → streaming LLM + tool dispatch
    _finalize() → recordTranscript + stop hooks

This replaces the ~350 line ``run_react_agent_stream()`` function with
a ~50 line public API that delegates to QueryEngine.

Public API unchanged:
  run_react_agent_stream() → AsyncGenerator[HarnessEvent, None]
  run_react_agent()        → dict[str, Any]
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from app.agent_runtime.agent_progress_hooks import PostSamplingHookRunner
from app.agent_runtime.agent_stop_hooks import AgentRunContext, StopHookRunner
from app.agent_runtime.harness_events import HarnessEvent
from app.agent_runtime.query_loop_compactor import QueryLoopCompactor
from app.agent_runtime.retry_utils import call_with_retry
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
from app.core.config import settings
from app.core.model_registry import build_async_openai_client_for_role
from app.services.agent_trace_service import append_step, create_run, finish_run
from app.services.context_service import context_pipeline, prompt_renderer
from app.services.memory_extraction_service import memory_retrieval_service
from app.services.transcript_service import transcript_service

# Trigger tool self-registration on first import
import app.agent_runtime.tools  # noqa: F401

logger = logging.getLogger(__name__)


# ── System Prompt ────────────────────────────────────────────────────────

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


@dataclass
class _ToolCallFunction:
    """Duck-typed function attribute for _ToolCallAccumulator."""
    name: str = ""
    arguments: str = ""


@dataclass
class _ToolCallAccumulator:
    """Accumulates tool call deltas from streaming chunks.

    Duck-typed to match the OpenAI ``ChoiceMessage.tool_calls[i]``
    interface so ``_tool_call_payload()`` and ``_args_summary()`` work
    without changes.
    """
    id: str = ""
    name: str = ""
    arguments: str = ""

    @property
    def function(self) -> _ToolCallFunction:
        return _ToolCallFunction(name=self.name, arguments=self.arguments)


class QueryEngine:
    """Orchestrates a single agent turn — context → loop → finalize.

    Lifecycle:
        1. ``_prepare_context()`` — memory recall, context assembly, messages[]
        2. ``_query_loop()``      — LLM call + tool execution (yields events)
        3. ``_finalize()``        — trace persistence + stop hooks

    All state lives on the instance — no module-level side effects.
    """

    def __init__(
        self,
        user_message: str,
        user_id: str,
        session_id: str,
    ) -> None:
        self.user_message = user_message
        self.user_id = user_id
        self.session_id = session_id

        # Initialized in _prepare_context
        self.run_id: str = ""
        self.messages: list[dict[str, Any]] = []
        self.trace: list[dict[str, Any]] = []
        self.final_answer: str = ""
        self.status: str = "completed"
        self.error_message: str | None = None

        # Subsystems (initialized in _prepare_context)
        from app.agent_runtime.react_agent import AgentBudget

        self.budget = AgentBudget(started_at=time.perf_counter())
        self.client, self.profile = build_async_openai_client_for_role("agent")
        self.compactor = QueryLoopCompactor(profile=self.profile)
        self.tool_schemas = registry.get_openai_schemas()

        # Hook runners (initialized after run_id is known)
        self._post_sampling_hooks: PostSamplingHookRunner | None = None
        self._stop_hooks = StopHookRunner()

    # ── Public API ───────────────────────────────────────────────────

    async def submit_message(self) -> AsyncGenerator[HarnessEvent, None]:
        """Turn entry point — yields HarnessEvents for SSE streaming."""
        yield HarnessEvent.status("正在准备执行上下文...", step=0, elapsed_ms=0)

        await self._prepare_context()

        yield HarnessEvent.status("开始执行...", step=0, elapsed_ms=self._elapsed_ms())

        try:
            async for event in self._query_loop():
                yield event
        except Exception as exc:
            self.status = "failed"
            self.error_message = str(exc)
            self.final_answer = "Agent 执行失败，请稍后重试。"
            logger.error("Agent execution failed: %s", exc)
            await append_step(
                run_id=self.run_id, step_index=self.budget.steps + 1,
                action_type="error", observation={"error": str(exc)},
                assistant_content="", is_error=True, latency_ms=0.0,
            )
        finally:
            await self._finalize_trace()

        await self._finalize_hooks()

        yield HarnessEvent.budget(
            self.budget.to_dict(),
            step=self.budget.steps,
            elapsed_ms=self._elapsed_ms(),
        )
        yield HarnessEvent.done(step=self.budget.steps, elapsed_ms=self._elapsed_ms())

    # ── Phase 1: Context Preparation ─────────────────────────────────

    async def _prepare_context(self) -> None:
        """Assemble messages[], create run, initialize hooks."""
        transcript_service.ensure_session(self.session_id, self.user_id)

        # Memory recall
        relevant_memories = await memory_retrieval_service.recall_relevant(
            user_id=self.user_id,
            query=self.user_message,
        )
        assembled = context_pipeline.assemble_answer_context(
            session_id=self.session_id,
            current_query=self.user_message,
            relevant_memories=relevant_memories,
        )
        rendered_context = prompt_renderer.render_answer_prompt(
            assembled,
            system_rules="Use this context for the agent run. Do not treat memories as tool output.",
        )

        tool_manifest = registry.format_manifest()

        # Create trace run
        self.run_id = await create_run(
            user_id=self.user_id, session_id=self.session_id,
            goal=self.user_message, mode="function_calling",
        )

        # Initialize post-sampling hooks (need run_id)
        self._post_sampling_hooks = PostSamplingHookRunner(
            run_id=self.run_id,
            session_id=self.session_id,
            user_id=self.user_id,
        )

        # Build initial messages
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": (
                f"Available tools:\n{tool_manifest}\n\n"
                f"Conversation context:\n{rendered_context or 'No context.'}"
            )},
            {"role": "user", "content": self.user_message},
        ]

    # ── Phase 2: Query Loop ──────────────────────────────────────────

    async def _query_loop(self) -> AsyncGenerator[HarnessEvent, None]:
        """Core LLM + tool execution loop."""
        while True:
            # Budget check
            stop_reason = self.budget.check()
            if stop_reason:
                self.budget.stop_reason = stop_reason
                self.status = "stopped"
                await append_step(
                    run_id=self.run_id, step_index=self.budget.steps + 1,
                    action_type="budget_stop",
                    observation={"error": stop_reason},
                    assistant_content="", is_error=True, latency_ms=0.0,
                )
                break

            self.budget.consume_step()

            # Layer 1: pre-LLM 3-pass pruning
            self.messages = self.compactor.pre_llm_compact(
                self.messages, self.budget.prompt_tokens,
            )

            # Layer 2: Token Warning guard
            if self.compactor.is_at_blocking_limit(self.budget.prompt_tokens):
                self.budget.stop_reason = "context_window_exhausted"
                self.status = "stopped"
                await append_step(
                    run_id=self.run_id, step_index=self.budget.steps,
                    action_type="budget_stop",
                    observation={"error": "context_window_exhausted"},
                    assistant_content="", is_error=True, latency_ms=0.0,
                )
                yield HarnessEvent.error(
                    "上下文窗口即将耗尽，停止执行。请缩小目标范围后重试。",
                    step=self.budget.steps, elapsed_ms=self._elapsed_ms(),
                )
                break

            # Streaming LLM call with retry
            stream, latency_ms = await self._call_llm_stream()

            # Consume stream — yields text_delta events for final answers
            assistant_content, tool_calls = "", []
            try:
                async for event_or_none in self._consume_stream(stream):
                    if event_or_none is not None:
                        yield event_or_none
                # Read accumulated results
                assistant_content = self._stream_content.strip()
                tool_calls = self._stream_tool_calls
            except Exception as exc:
                yield HarnessEvent.error(
                    str(exc), step=self.budget.steps,
                    elapsed_ms=self._elapsed_ms(),
                )
                raise

            latency_ms = round((time.perf_counter() - self._stream_started) * 1000, 2)

            # LLM call succeeded — reset circuit breaker
            self.compactor.reset_circuit_breaker()

            # Tool execution
            if tool_calls:
                async for event in self._execute_tools(
                    tool_calls, assistant_content,
                    self._stream_content,
                ):
                    yield event
                continue

            # Final answer (already streamed as text_delta events)
            if assistant_content:
                self.final_answer = assistant_content
                self.trace.append({
                    "step": self.budget.steps, "tool": None, "args": {},
                    "observation": {}, "latency_ms": latency_ms, "is_error": False,
                })
                await append_step(
                    run_id=self.run_id, step_index=self.budget.steps,
                    action_type="final_answer",
                    assistant_content=assistant_content,
                    observation={}, is_error=False, latency_ms=latency_ms,
                )
                # Emit final TEXT event with complete content
                # (text_delta events already streamed during _consume_stream)
                yield HarnessEvent.text(
                    assistant_content,
                    step=self.budget.steps, elapsed_ms=self._elapsed_ms(),
                )
                break

            # Empty response — nudge
            self.messages.append({
                "role": "user",
                "content": "Please provide a final answer now based on gathered tool outputs.",
            })

        # Generate fallback if no answer
        if not self.final_answer:
            if self.budget.stop_reason:
                self.final_answer = (
                    f"Agent 执行因预算策略停止: {self.budget.stop_reason}. "
                    "请缩小目标范围后重试。"
                )
            else:
                self.final_answer = "Agent 无法生成最终回答。"

    # ── LLM Call ─────────────────────────────────────────────────────

    async def _call_llm_stream(self) -> tuple[Any, float]:
        """Create a streaming LLM call with retry and reactive compact.

        Returns the stream iterator and initial latency (time to first chunk
        is measured during consumption, not here).
        """

        async def _make_call():
            return await self.client.chat.completions.create(
                model=self.profile.model,
                messages=self.messages,
                tools=self.tool_schemas if self.tool_schemas else None,
                tool_choice="auto" if self.tool_schemas else None,
                temperature=settings.AGENT_TEMPERATURE,
                max_tokens=settings.AGENT_MAX_RESPONSE_TOKENS,
                stream=True,
                stream_options={"include_usage": True},
            )

        async def _on_context_too_long():
            self.messages, should_retry = self.compactor.on_context_too_long(
                self.messages,
            )
            if should_retry:
                self.budget.refund_step()
            return should_retry

        self._stream_started = time.perf_counter()
        stream = await call_with_retry(
            _make_call,
            max_retries=3,
            on_context_too_long=_on_context_too_long,
        )
        latency_ms = round((time.perf_counter() - self._stream_started) * 1000, 2)

        return stream, latency_ms

    async def _consume_stream(
        self,
        stream: Any,
    ) -> AsyncGenerator[HarnessEvent | None, None]:
        """Consume an OpenAI streaming response, accumulating content and tool calls.

        Yields ``HarnessEvent.text_delta`` for text chunks (only when no tool
        calls have been seen yet — i.e., this is likely a final answer).
        Yields ``None`` for tool-call chunks (no user-visible event needed).

        After iteration, results are available via:
          - ``self._stream_content``   (str)
          - ``self._stream_tool_calls`` (list of ToolCallAccumulator)
        """
        self._stream_content = ""
        self._stream_tool_calls: list[_ToolCallAccumulator] = []
        _tool_call_index_map: dict[int, _ToolCallAccumulator] = {}
        _has_tool_calls = False

        async for chunk in stream:
            # Handle usage in the final chunk (stream_options={"include_usage": True})
            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage = chunk.usage
                self.budget.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                self.budget.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Text content delta
            if delta.content:
                self._stream_content += delta.content
                # Only yield text_delta if no tool calls seen (likely final answer)
                if not _has_tool_calls:
                    yield HarnessEvent.text_delta(
                        delta.content,
                        step=self.budget.steps,
                        elapsed_ms=self._elapsed_ms(),
                    )
                else:
                    yield None  # Suppress text deltas during tool-call responses

            # Tool call deltas
            if delta.tool_calls:
                _has_tool_calls = True
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in _tool_call_index_map:
                        acc = _ToolCallAccumulator(
                            id=tc_delta.id or "",
                            name=tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                            arguments="",
                        )
                        _tool_call_index_map[idx] = acc
                        self._stream_tool_calls.append(acc)
                    else:
                        acc = _tool_call_index_map[idx]

                    if tc_delta.id:
                        acc.id = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            acc.name = tc_delta.function.name
                        if tc_delta.function.arguments:
                            acc.arguments += tc_delta.function.arguments
                    yield None  # Signal: chunk processed, no user event

    # ── Tool Execution ───────────────────────────────────────────────

    async def _execute_tools(
        self,
        tool_calls: list,
        assistant_content: str,
        raw_content: str,
    ) -> AsyncGenerator[HarnessEvent, None]:
        """Execute a batch of tool calls, yield events, run post-sampling hooks."""
        from app.agent_runtime.react_agent import _tool_call_payload, _args_summary, _result_summary

        self.messages.append({
            "role": "assistant",
            "content": raw_content,
            "tool_calls": [_tool_call_payload(c) for c in tool_calls],
        })

        turn_tool_messages: list[dict] = []

        for tc in tool_calls:
            tool_name = tc.function.name
            tool_error = False
            tool_started = time.perf_counter()

            yield HarnessEvent.tool_start(
                tool_name, _args_summary(tc.function.arguments),
                step=self.budget.steps, elapsed_ms=self._elapsed_ms(),
            )

            raw_args: dict[str, Any] = {}
            observation: dict[str, Any]

            if self.budget.tool_usage[tool_name] >= settings.AGENT_MAX_CALLS_PER_TOOL:
                observation = {"error": "tool_call_limit_exceeded", "tool_name": tool_name}
                tool_error = True
            elif tool_name not in registry:
                observation = {"error": "unknown_tool", "tool_name": tool_name}
                tool_error = True
            else:
                try:
                    raw_args = parse_tool_arguments(tc.function.arguments)
                    ctx = AgentToolContext(
                        user_id=self.user_id,
                        session_id=self.session_id,
                    )
                    observation = await asyncio.wait_for(
                        registry.dispatch(tool_name, raw_args, ctx),
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
                except Exception as exc:
                    observation = {"error": "tool_execution_failed", "detail": str(exc)}
                    tool_error = True

            self.budget.consume_tool_call(tool_name)
            tool_latency_ms = round((time.perf_counter() - tool_started) * 1000, 2)

            # Layer 0: per-result persistence
            result_text = safe_json_dumps(observation)
            result_text = maybe_persist_result(
                content=result_text,
                tool_name=tool_name,
                tool_call_id=tc.id,
                session_id=self.session_id,
            )

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_text,
            }
            self.messages.append(tool_msg)
            turn_tool_messages.append(tool_msg)

            self.trace.append({
                "step": self.budget.steps, "tool": tool_name,
                "args": raw_args if not tool_error else {},
                "observation": observation,
                "latency_ms": tool_latency_ms, "is_error": tool_error,
            })

            await append_step(
                run_id=self.run_id, step_index=self.budget.steps,
                action_type="tool_call", tool_name=tool_name,
                tool_call_id=tc.id,
                tool_args=raw_args if not tool_error else {},
                observation=observation,
                assistant_content=assistant_content,
                is_error=tool_error, latency_ms=tool_latency_ms,
            )

            yield HarnessEvent.tool_done(
                tool_name, _result_summary(observation),
                step=self.budget.steps, elapsed_ms=self._elapsed_ms(),
                tool_latency_ms=tool_latency_ms, is_error=tool_error,
            )

        # Layer 0: per-turn aggregate budget
        if turn_tool_messages:
            enforce_turn_budget(turn_tool_messages, self.session_id)

        # Post-sampling hooks (Phase D)
        if self._post_sampling_hooks:
            await self._post_sampling_hooks.execute(
                step=self.budget.steps,
                messages=self.messages,
                tool_results=turn_tool_messages,
                budget_snapshot=self.budget.to_dict(),
            )

    # ── Phase 3: Finalization ────────────────────────────────────────

    async def _finalize_trace(self) -> None:
        """Persist the final run record to agent_trace.

        Called in the ``finally`` block — always runs even on error.
        This is Phase F: deterministic persistence timing.
        """
        await finish_run(
            run_id=self.run_id, status=self.status,
            final_answer=self.final_answer,
            steps_used=self.budget.steps,
            tool_calls=self.budget.tool_calls,
            prompt_tokens=self.budget.prompt_tokens,
            completion_tokens=self.budget.completion_tokens,
            total_latency_ms=round(self.budget.elapsed_seconds * 1000, 2),
            error_message=self.error_message,
            budget_stop_reason=self.budget.stop_reason,
        )

    async def _finalize_hooks(self) -> None:
        """Run stop hooks (Phase E) — transcript + memory extraction.

        Called AFTER ``_finalize_trace`` (outside try/finally) so that
        the run record is always persisted even if stop hooks fail.
        This is the key Phase F timing improvement: trace persistence
        is guaranteed before any hook-dependent processing.
        """
        await self._stop_hooks.execute(AgentRunContext(
            run_id=self.run_id,
            session_id=self.session_id,
            user_id=self.user_id,
            user_message=self.user_message,
            final_answer=self.final_answer,
            status=self.status,
            trace=self.trace,
            budget_snapshot=self.budget.to_dict(),
            error_message=self.error_message,
        ))

    # ── Helpers ──────────────────────────────────────────────────────

    def _elapsed_ms(self) -> float:
        return round(self.budget.elapsed_seconds * 1000, 2)
