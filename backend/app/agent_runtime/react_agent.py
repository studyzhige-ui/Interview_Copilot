"""Agent harness primitives — run-state telemetry + streaming helpers.

The actual agent loop lives in
:class:`app.conversation.agent_strategy.AgentLoopStrategy`, and the
per-conversation lifecycle in
:class:`app.conversation.engine.ConversationEngine`. Agent turns enter
through the durable conversation-turn API; this module only provides
loop primitives.

What this module retains:

  - ``AgentRunState``      — per-turn usage and progress telemetry
  - ``_tool_call_payload`` — OpenAI tool_calls dict shape
  - ``_args_summary``      — short label for the SSE tool_start event
  - ``_result_summary``    — short label for the SSE tool_done event
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# ── Agent run state ──────────────────────────────────────────────────────


@dataclass
class AgentRunState:
    """Observed usage and loop progress for one turn.

    Steps, tool calls, tokens, and elapsed time are telemetry. They never stop
    a valid task. Completion comes from the model, an explicit cancellation,
    context-window exhaustion, or the surrounding worker/process lifecycle.
    """

    started_at: float
    steps: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stop_reason: str | None = None
    tool_usage: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    tool_signatures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    tool_call_ids: set[str] = field(default_factory=set)
    last_failed_outcome: tuple[str, str] | None = None
    failed_outcome_streak: int = 0
    last_action: tuple[str, str] | None = None
    no_progress_streak: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    def consume_step(self) -> None:
        self.steps += 1

    def consume_tool_call(self, tool_name: str, signature: str = "") -> int:
        """Record a tool call; return the repeat count for *signature*.

        ``signature`` identifies a (tool, args) pair so the loop can softly
        nudge on identical repeated calls. Returns how many times this exact
        signature has been seen (0 when no signature is given).
        """
        self.tool_calls += 1
        self.tool_usage[tool_name] += 1
        if not signature:
            return 0
        self.tool_signatures[signature] += 1
        return self.tool_signatures[signature]

    def refund_step(self) -> None:
        """Exclude a compression retry from observed reasoning-step usage."""
        if self.steps > 0:
            self.steps -= 1

    def observe_tool_result(
        self,
        tool_name: str,
        signature: str,
        result: str,
        *,
        is_error: bool,
    ) -> str | None:
        """Detect repeated failures or unchanged outcomes and request replanning."""
        fingerprint = hashlib.sha256(result.encode("utf-8")).hexdigest()[:16]
        failed = (signature, fingerprint)
        if is_error:
            self.failed_outcome_streak = (
                self.failed_outcome_streak + 1
                if self.last_failed_outcome == failed
                else 1
            )
            self.last_failed_outcome = failed
        else:
            self.failed_outcome_streak = 0
            self.last_failed_outcome = None

        action = (tool_name, fingerprint)
        self.no_progress_streak = (
            self.no_progress_streak + 1 if self.last_action == action else 1
        )
        self.last_action = action
        if self.failed_outcome_streak >= 3:
            self.failed_outcome_streak = 0
            return "The same tool call failed with the same outcome three times. Stop retrying and replan."
        if self.no_progress_streak >= 4:
            self.no_progress_streak = 0
            return "Four tool actions produced no new outcome. Pause the current approach and replan from the evidence."
        return None

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
            "name": tool_call.name
            if hasattr(tool_call, "name")
            else tool_call.function.name,
            "arguments": tool_call.arguments
            if hasattr(tool_call, "arguments")
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
    "AgentRunState",
    "_args_summary",
    "_result_summary",
    "_tool_call_payload",
]
