"""Agent Harness — unified ReAct execution engine.

Complete rewrite of the agent loop with:
  - ToolRegistry integration (replacing hardcoded tool list)
  - Domain-specific system prompt
  - Error retry with jittered backoff (Hermes pattern)
  - Context compaction for long tool chains (Hermes pattern)
  - Structured HarnessEvent emission for frontend visualization
  - Budget refund on tool failures
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from app.core.background_tasks import safe_background_task
from app.agent_runtime.context_compactor import AgentContextCompactor
from app.agent_runtime.harness_events import HarnessEvent
from app.agent_runtime.retry_utils import ErrorCategory, call_with_retry, classify_api_error
from app.agent_runtime.tool_registry import (
    AgentToolContext,
    parse_tool_arguments,
    registry,
    safe_json_dumps,
)
from app.core.config import settings
from app.core.model_registry import build_async_openai_client_for_role
from app.services.agent_trace_service import append_step, create_run, finish_run
from app.services.context_service import context_pipeline, prompt_renderer
from app.services.memory_extraction_service import (
    memory_retrieval_service,
    post_turn_maintenance_service,
)
from app.services.transcript_service import transcript_service

# Trigger tool self-registration on first import
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




@dataclass
class AgentBudget:
    """Lightweight iteration budget — Hermes-style.

    Design: only two hard limits (steps + wall-clock timeout), both of
    which are essential for a Web-served agent.  Token usage and tool
    call counts are *tracked* for observability but do NOT trigger
    early stops — the ContextCompactor handles context window pressure
    adaptively, which is far superior to a hard token cap.

    Per-tool call limits are the sole loop-prevention safety valve.
    """

    started_at: float
    steps: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stop_reason: str | None = None
    tool_usage: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    def check(self) -> str | None:
        """Check budget — only steps and wall-clock timeout.

        Token usage and total tool calls are tracked for observability
        but never trigger stops. Context window pressure is handled by
        AgentContextCompactor adaptively.
        """
        if self.steps >= settings.AGENT_MAX_STEPS:
            return "max_steps_exceeded"
        if self.elapsed_seconds >= settings.AGENT_MAX_RUNTIME_SECONDS:
            return "runtime_timeout"
        return None

    def consume_step(self) -> None:
        self.steps += 1

    def consume_tool_call(self, tool_name: str) -> None:
        self.tool_calls += 1
        self.tool_usage[tool_name] += 1

    def refund_step(self) -> None:
        """Refund a step on tool failure (Hermes pattern)."""
        if self.steps > 0:
            self.steps -= 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "elapsed_s": round(self.elapsed_seconds, 2),
        }


def _elapsed_ms(budget: AgentBudget) -> float:
    return round(budget.elapsed_seconds * 1000, 2)


def _tool_call_payload(tool_call: Any) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
        },
    }


def _observation_for_llm(observation: Any, max_chars: int = 6000) -> str:
    text = safe_json_dumps(observation)
    return text if len(text) <= max_chars else text[:max_chars] + "...(truncated)"


def _args_summary(raw_args: str) -> str:
    """Short summary of tool arguments for event display."""
    try:
        import json
        parsed = json.loads(raw_args) if raw_args else {}
        parts = []
        for k, v in list(parsed.items())[:3]:
            val = str(v)[:60]
            parts.append(f"{k}={val}")
        return ", ".join(parts)
    except Exception:
        return raw_args[:80] if raw_args else ""


def _result_summary(observation: dict[str, Any]) -> str:
    """Short summary of tool result for event display."""
    if "error" in observation:
        return f"❌ {observation['error']}"
    if "count" in observation:
        return f"返回 {observation['count']} 条结果"
    if "content" in observation:
        content = str(observation["content"])
        return f"提取 {len(content)} 字"
    if "action" in observation:
        return f"✅ {observation['action']}"
    if "message" in observation:
        return str(observation["message"])[:100]
    return f"✅ 完成 ({len(str(observation))} chars)"


# ── Streaming variant ────────────────────────────────────────────────────

async def run_react_agent_stream(
    user_message: str,
    user_id: str,
    session_id: str,
) -> AsyncGenerator[HarnessEvent, None]:
    """Run the agent loop, yielding HarnessEvents for SSE streaming."""

    yield HarnessEvent.status("正在准备执行上下文...", step=0, elapsed_ms=0)

    transcript_service.ensure_session(session_id, user_id)

    # Agent link is user-initiated — no planner routing needed.
    # Directly recall memories using the raw user message.
    relevant_memories = await memory_retrieval_service.recall_relevant(
        user_id=user_id,
        query=user_message,
    )
    assembled = context_pipeline.assemble_answer_context(
        session_id=session_id,
        current_query=user_message,
        relevant_memories=relevant_memories,
    )
    rendered_context = prompt_renderer.render_answer_prompt(
        assembled,
        system_rules="Use this context for the agent run. Do not treat memories as tool output.",
    )

    tool_schemas = registry.get_openai_schemas()
    tool_manifest = registry.format_manifest()

    run_id = await create_run(
        user_id=user_id, session_id=session_id,
        goal=user_message, mode="function_calling",
    )

    budget = AgentBudget(started_at=time.perf_counter())
    compactor = AgentContextCompactor()
    trace: list[dict[str, Any]] = []
    final_answer = ""
    status = "completed"
    error_message: str | None = None

    client, agent_profile = build_async_openai_client_for_role("agent")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": (
            f"Available tools:\n{tool_manifest}\n\n"
            f"Conversation context:\n{rendered_context or 'No context.'}"
        )},
        {"role": "user", "content": user_message},
    ]

    yield HarnessEvent.status("开始执行...", step=0, elapsed_ms=_elapsed_ms(budget))

    try:
        while True:
            stop_reason = budget.check()
            if stop_reason:
                budget.stop_reason = stop_reason
                status = "stopped"
                await append_step(
                    run_id=run_id, step_index=budget.steps + 1,
                    action_type="budget_stop",
                    observation={"error": stop_reason},
                    assistant_content="", is_error=True, latency_ms=0.0,
                )
                break

            budget.consume_step()

            # LLM call with retry
            async def _make_llm_call():
                return await client.chat.completions.create(
                    model=agent_profile.model,
                    messages=messages,
                    tools=tool_schemas if tool_schemas else None,
                    tool_choice="auto" if tool_schemas else None,
                    temperature=settings.AGENT_TEMPERATURE,
                    max_tokens=settings.AGENT_MAX_RESPONSE_TOKENS,
                )

            async def _on_context_too_long():
                nonlocal messages
                messages = compactor.prune_old_tool_results(messages)
                return True

            started = time.perf_counter()
            try:
                response = await call_with_retry(
                    _make_llm_call,
                    max_retries=3,
                    on_context_too_long=_on_context_too_long,
                )
            except Exception as exc:
                yield HarnessEvent.error(str(exc), step=budget.steps, elapsed_ms=_elapsed_ms(budget))
                raise

            latency_ms = round((time.perf_counter() - started) * 1000, 2)

            usage = response.usage
            if usage:
                budget.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                budget.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

            choice = response.choices[0]
            message = choice.message
            assistant_content = (message.content or "").strip()
            tool_calls = list(message.tool_calls or [])

            # ── Tool execution ───────────────────────────────────
            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [_tool_call_payload(c) for c in tool_calls],
                })

                for tc in tool_calls:
                    tool_name = tc.function.name
                    tool_error = False
                    tool_started = time.perf_counter()

                    yield HarnessEvent.tool_start(
                        tool_name, _args_summary(tc.function.arguments),
                        step=budget.steps, elapsed_ms=_elapsed_ms(budget),
                    )

                    if budget.tool_usage[tool_name] >= settings.AGENT_MAX_CALLS_PER_TOOL:
                        observation = {"error": "tool_call_limit_exceeded", "tool_name": tool_name}
                        tool_error = True
                    elif tool_name not in registry:
                        observation = {"error": "unknown_tool", "tool_name": tool_name}
                        tool_error = True
                    else:
                        try:
                            raw_args = parse_tool_arguments(tc.function.arguments)
                            ctx = AgentToolContext(user_id=user_id, session_id=session_id)
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

                    budget.consume_tool_call(tool_name)
                    tool_latency_ms = round((time.perf_counter() - tool_started) * 1000, 2)

                    # Refund step on tool failure (Hermes pattern)
                    if tool_error:
                        budget.refund_step()

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _observation_for_llm(observation),
                    })

                    trace.append({
                        "step": budget.steps, "tool": tool_name,
                        "args": raw_args if not tool_error else {},
                        "observation": observation,
                        "latency_ms": tool_latency_ms, "is_error": tool_error,
                    })

                    await append_step(
                        run_id=run_id, step_index=budget.steps,
                        action_type="tool_call", tool_name=tool_name,
                        tool_call_id=tc.id,
                        tool_args=raw_args if not tool_error else {},
                        observation=observation,
                        assistant_content=assistant_content,
                        is_error=tool_error, latency_ms=tool_latency_ms,
                    )

                    yield HarnessEvent.tool_done(
                        tool_name, _result_summary(observation),
                        step=budget.steps, elapsed_ms=_elapsed_ms(budget),
                        tool_latency_ms=tool_latency_ms, is_error=tool_error,
                    )

                # Context compaction check after tool batch
                if compactor.should_compact(budget.prompt_tokens):
                    messages = compactor.prune_old_tool_results(messages)

                continue

            # ── Final answer ─────────────────────────────────────
            if assistant_content:
                final_answer = assistant_content
                trace.append({
                    "step": budget.steps, "tool": None, "args": {},
                    "observation": {}, "latency_ms": latency_ms, "is_error": False,
                })
                await append_step(
                    run_id=run_id, step_index=budget.steps,
                    action_type="final_answer",
                    assistant_content=assistant_content,
                    observation={}, is_error=False, latency_ms=latency_ms,
                )
                yield HarnessEvent.text(assistant_content, step=budget.steps, elapsed_ms=_elapsed_ms(budget))
                break

            # Empty response — nudge
            messages.append({
                "role": "user",
                "content": "Please provide a final answer now based on gathered tool outputs.",
            })

        if not final_answer:
            if budget.stop_reason:
                final_answer = (
                    f"Agent 执行因预算策略停止: {budget.stop_reason}. "
                    "请缩小目标范围后重试。"
                )
            else:
                final_answer = "Agent 无法生成最终回答。"

    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        final_answer = "Agent 执行失败，请稍后重试。"
        logger.error("Agent execution failed: %s", exc)
        await append_step(
            run_id=run_id, step_index=budget.steps + 1,
            action_type="error", observation={"error": str(exc)},
            assistant_content="", is_error=True, latency_ms=0.0,
        )
    finally:
        await finish_run(
            run_id=run_id, status=status, final_answer=final_answer,
            steps_used=budget.steps, tool_calls=budget.tool_calls,
            prompt_tokens=budget.prompt_tokens,
            completion_tokens=budget.completion_tokens,
            total_latency_ms=round(budget.elapsed_seconds * 1000, 2),
            error_message=error_message,
            budget_stop_reason=budget.stop_reason,
        )

    transcript_service.append_turn(
        session_id=session_id, user_id=user_id,
        user_msg=user_message, ai_msg=final_answer,
    )
    # Agent mode always allows memory write — the agent actively manages
    # user knowledge through save_memory tool calls.
    safe_background_task(
        post_turn_maintenance_service.run(session_id, user_id, allow_memory_write=True)
    )

    yield HarnessEvent.budget(budget.to_dict(), step=budget.steps, elapsed_ms=_elapsed_ms(budget))
    yield HarnessEvent.done(step=budget.steps, elapsed_ms=_elapsed_ms(budget))


# ── Batch variant (API compatible with old run_react_agent) ──────────────

async def run_react_agent(
    user_message: str,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Batch execution — collects all events and returns the final result dict.

    This preserves full API compatibility with the old ``run_react_agent``.
    """
    events: list[HarnessEvent] = []
    final_answer = ""
    budget_info: dict[str, Any] = {}
    run_id = ""

    async for event in run_react_agent_stream(user_message, user_id, session_id):
        events.append(event)
        if event.type.value == "text":
            final_answer = event.data.get("content", "")
        elif event.type.value == "budget":
            budget_info = event.data

    # Extract run_id from trace service (it's set inside the stream)
    trace = [
        e.to_dict() for e in events
        if e.type.value in ("tool_start", "tool_done", "error")
    ]

    return {
        "run_id": "",  # run_id is managed internally by the stream
        "reply": final_answer,
        "trace": trace,
        "steps_used": budget_info.get("steps", 0),
        "tool_calls": budget_info.get("tool_calls", 0),
        "prompt_tokens": budget_info.get("prompt_tokens", 0),
        "completion_tokens": budget_info.get("completion_tokens", 0),
        "budget_stop_reason": None,
    }
