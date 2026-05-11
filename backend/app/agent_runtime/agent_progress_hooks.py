"""Post-sampling hooks for the Agent Harness query loop.

Runs after each tool batch execution completes.  Provides an extensible
hook system for progress checkpointing, metrics, and observability.

Design reference (Claude Code query.ts):
  Query Loop ④ Post-Sampling Hooks — executed after each LLM response
  is processed.  Claude Code uses this to update Session Memory.

Our adaptation:
  Hooks run after *tool execution* (not just LLM response), so progress
  checkpoints capture tool results — more useful for crash recovery.

Architecture:
  PostSamplingHook  — protocol for individual hooks
  PostSamplingHookRunner — orchestrator that runs all hooks in order
  ProgressCheckpointHook — concrete hook: writes progress to agent_trace

All hooks are fire-and-forget at the individual level: a failing hook
never interrupts the query loop.  Errors are logged for observability.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Hook Protocol ────────────────────────────────────────────────────────


@dataclass
class PostSamplingContext:
    """Read-only snapshot passed to each post-sampling hook.

    Contains everything a hook needs to observe the current state
    without being able to modify the query loop.
    """

    run_id: str
    session_id: str
    user_id: str
    step: int
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]  # tool messages from this turn
    budget_snapshot: dict[str, Any]


class PostSamplingHook(ABC):
    """Base class for post-sampling hooks."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable hook name for logging."""

    @abstractmethod
    async def run(self, ctx: PostSamplingContext) -> None:
        """Execute the hook.  Must not raise — errors are caught by runner."""


# ── Concrete Hooks ───────────────────────────────────────────────────────


class ProgressCheckpointHook(PostSamplingHook):
    """Write a progress checkpoint to agent_trace after each tool batch.

    Uses the existing ``append_step`` API with ``action_type='checkpoint'``
    so no new DB tables are needed.  Checkpoints include:
      - Step index
      - Summary of tool results from this turn
      - Token usage snapshot

    This enables crash recovery: if the agent crashes at step 12, the
    first 11 steps are already persisted as checkpoints.
    """

    # Only checkpoint every N steps to avoid excessive DB writes.
    # Steps that produce significant tool results are always checkpointed.
    _CHECKPOINT_INTERVAL = 3

    # Tool results larger than this (chars) are considered "significant"
    _SIGNIFICANT_RESULT_CHARS = 500

    @property
    def name(self) -> str:
        return "ProgressCheckpoint"

    async def run(self, ctx: PostSamplingContext) -> None:
        # Decide whether to checkpoint this step
        has_significant_result = any(
            len(tr.get("content", "")) > self._SIGNIFICANT_RESULT_CHARS
            for tr in ctx.tool_results
        )
        at_interval = (ctx.step % self._CHECKPOINT_INTERVAL) == 0

        if not has_significant_result and not at_interval:
            return

        # Build checkpoint summary
        tool_summary_parts = []
        for tr in ctx.tool_results:
            content = tr.get("content", "")
            tool_call_id = tr.get("tool_call_id", "?")
            # Find tool name from messages
            tool_name = _find_tool_name_for_call_id(ctx.messages, tool_call_id)
            size = len(content)
            preview = content[:80].replace("\n", " ")
            tool_summary_parts.append(
                f"{tool_name}({tool_call_id}): {size} chars — {preview}"
            )

        checkpoint_data = {
            "step": ctx.step,
            "tool_count": len(ctx.tool_results),
            "tools_summary": tool_summary_parts[:5],  # cap at 5
            "budget": ctx.budget_snapshot,
        }

        from app.services.agent_trace_service import append_step

        await append_step(
            run_id=ctx.run_id,
            step_index=ctx.step,
            action_type="checkpoint",
            observation=checkpoint_data,
            assistant_content="",
            is_error=False,
            latency_ms=0.0,
        )

        logger.debug(
            "Progress checkpoint at step %d (%d tools)",
            ctx.step,
            len(ctx.tool_results),
        )


# ── Runner ───────────────────────────────────────────────────────────────


class PostSamplingHookRunner:
    """Orchestrates post-sampling hooks after each tool batch.

    Hooks run sequentially in registration order.  Each hook is
    individually guarded — a failing hook never interrupts the loop
    or prevents subsequent hooks from running.
    """

    def __init__(
        self,
        *,
        run_id: str,
        session_id: str,
        user_id: str,
    ):
        self.run_id = run_id
        self.session_id = session_id
        self.user_id = user_id
        self._hooks: list[PostSamplingHook] = [
            ProgressCheckpointHook(),
        ]

    async def execute(
        self,
        *,
        step: int,
        messages: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        budget_snapshot: dict[str, Any],
    ) -> None:
        """Run all hooks with the current context.

        Called by the agent loop after all tools in a step complete.
        """
        ctx = PostSamplingContext(
            run_id=self.run_id,
            session_id=self.session_id,
            user_id=self.user_id,
            step=step,
            messages=messages,
            tool_results=tool_results,
            budget_snapshot=budget_snapshot,
        )
        for hook in self._hooks:
            try:
                await hook.run(ctx)
            except Exception as exc:
                logger.warning(
                    "Post-sampling hook '%s' failed at step %d: %s",
                    hook.name,
                    step,
                    exc,
                )


# ── Helpers ──────────────────────────────────────────────────────────────


def _find_tool_name_for_call_id(
    messages: list[dict[str, Any]], tool_call_id: str
) -> str:
    """Walk backward through messages to find the tool name."""
    if not tool_call_id:
        return "unknown"
    for msg in reversed(messages):
        for tc in msg.get("tool_calls", []):
            if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                return tc.get("function", {}).get("name", "unknown")
    return "unknown"
