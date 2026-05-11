"""Agent Harness — public API and shared types.

The heavy lifting has been extracted to ``QueryEngine`` (Phase A).
This module retains:

  - ``AgentBudget`` — iteration budget dataclass (used by tests + QueryEngine)
  - Helper functions — ``_tool_call_payload``, ``_args_summary``, ``_result_summary``
  - ``run_react_agent_stream()`` — streaming public API (delegates to QueryEngine)
  - ``run_react_agent()`` — batch public API (wraps streaming variant)

Design: keeps the public API surface identical so ``__init__.py``
and all callers work without any import changes.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from app.agent_runtime.harness_events import HarnessEvent
from app.core.config import settings


# ── AgentBudget ──────────────────────────────────────────────────────────


@dataclass
class AgentBudget:
    """Lightweight iteration budget — Hermes-style.

    Design: only two hard limits (steps + wall-clock timeout), both of
    which are essential for a Web-served agent.  Token usage and tool
    call counts are *tracked* for observability but do NOT trigger
    early stops — the QueryLoopCompactor handles context window pressure
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
        QueryLoopCompactor adaptively.
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
        """Refund a step on compression-retry (Hermes L12974 pattern).

        Called when the system retries after context compaction — the
        retry is a system-level action, not agent reasoning.

        NOT called on tool failure — LLM already made a reasoning
        decision that should count toward the step budget.
        """
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


# ── Helper Functions ─────────────────────────────────────────────────────
# These are used by QueryEngine for event formatting.


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


# ── Streaming Public API ─────────────────────────────────────────────────


async def run_react_agent_stream(
    user_message: str,
    user_id: str,
    session_id: str,
) -> AsyncGenerator[HarnessEvent, None]:
    """Run the agent loop, yielding HarnessEvents for SSE streaming.

    Delegates all logic to ``QueryEngine.submit_message()``.
    """
    from app.agent_runtime.query_engine import QueryEngine

    engine = QueryEngine(user_message, user_id, session_id)
    async for event in engine.submit_message():
        yield event


# ── Batch Public API ─────────────────────────────────────────────────────


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

    async for event in run_react_agent_stream(user_message, user_id, session_id):
        events.append(event)
        if event.type.value == "text":
            final_answer = event.data.get("content", "")
        elif event.type.value == "budget":
            budget_info = event.data

    trace = [
        e.to_dict() for e in events
        if e.type.value in ("tool_start", "tool_done", "error")
    ]

    return {
        "run_id": "",  # run_id is managed internally by the engine
        "reply": final_answer,
        "trace": trace,
        "steps_used": budget_info.get("steps", 0),
        "tool_calls": budget_info.get("tool_calls", 0),
        "prompt_tokens": budget_info.get("prompt_tokens", 0),
        "completion_tokens": budget_info.get("completion_tokens", 0),
        "budget_stop_reason": None,
    }
