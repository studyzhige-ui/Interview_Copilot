"""Agent harness primitives — ``AgentBudget`` + streaming helpers.

The actual agent loop lives in
:class:`app.conversation.agent_strategy.AgentLoopStrategy`, and the
per-conversation lifecycle in
:class:`app.conversation.engine.ConversationEngine`. The legacy
``run_react_agent`` / ``run_react_agent_stream`` shims that wrapped
the engine for the old ``/agent/react/*`` endpoints were deleted in
the audit cleanup — the unified ``/chat/sse`` (mode=agent) is the
sole entry point now.

What this module retains:

  - ``AgentBudget``        — iteration budget dataclass
  - ``_tool_call_payload`` — OpenAI tool_calls dict shape
  - ``_args_summary``      — short label for the SSE tool_start event
  - ``_result_summary``    — short label for the SSE tool_done event
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

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
        """Refund a step on compression-retry (Hermes L12974 pattern)."""
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


# ── Streaming event formatting helpers ──────────────────────────────────


def _tool_call_payload(tool_call: Any) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.name if hasattr(tool_call, "name") else tool_call.function.name,
            "arguments": tool_call.arguments if hasattr(tool_call, "arguments")
                          else tool_call.function.arguments,
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
    """Short, HONEST summary of a tool result for event display.

    Order matters — check the "negative" signals first (disabled,
    error) so they never fall through to a misleading "✅ 完成 (N
    chars)" line. Pre-fix screenshot: ``recall_memory`` returning
    ``{"disabled": true, "reason": "用户已关闭…"}`` rendered as
    "✅ 完成 (273 chars)" — the 273 chars were the JSON of the
    refusal payload. That looked like success to the user.
    """
    # Privacy/gate refusal — tool returned a structured "I won't run"
    # payload (recall_memory / save_memory under global-memory off).
    if observation.get("disabled") is True:
        reason = observation.get("reason") or "已禁用"
        return f"⊘ {str(reason)[:100]}"

    # Hard error from the handler.
    if "error" in observation:
        return f"❌ {observation['error']}"

    # Empty-result patterns — surface them so the LLM (and the user)
    # see "0 条" without ambiguity. (Previously a 0-count could fall
    # through to the byte-counter fallback and look like a successful
    # "完成" payload — the dedicated branch below fixes that.)
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


__all__ = [
    "AgentBudget",
    "_args_summary",
    "_result_summary",
    "_tool_call_payload",
]
