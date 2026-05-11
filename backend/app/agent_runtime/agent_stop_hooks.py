"""Stop hooks for the Agent Harness — post-run lifecycle management.

Runs when the agent finishes (final answer produced, budget exceeded,
or error caught).  Replaces the hardcoded fire-and-forget post-processing
in react_agent.py with an extensible, ordered hook pipeline.

Design reference (Claude Code query.ts):
  Query Loop ⑥ Stop Hooks:
    - ExtractMemories → long-term memory extraction
    - AutoDream → memory consolidation
    - PromptSuggestion → suggest next actions

Our hooks:
  1. TranscriptPersistenceHook — append the user↔assistant turn
  2. MemoryExtractionHook — extract & merge long-term memories
  3. SessionCompactionHook — compact session if needed (compaction service)

Architecture:
  StopHook — protocol for individual hooks
  AgentRunContext — immutable context snapshot for hooks
  StopHookRunner — orchestrator that runs all hooks in order

Key improvement over the old approach:
  - Hooks run in defined order (transcript → memory → compaction)
  - Failures are logged and observable (not fire-and-forget)
  - New hooks can be added without modifying react_agent.py
  - Each hook receives the full run context including tool trace
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Context ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentRunContext:
    """Immutable snapshot of a completed agent run.

    Passed to each stop hook so it can observe the full run state.
    """

    run_id: str
    session_id: str
    user_id: str
    user_message: str
    final_answer: str
    status: str  # "completed", "stopped", "failed"
    trace: list[dict[str, Any]] = field(default_factory=list)
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


# ── Hook Protocol ────────────────────────────────────────────────────────


class StopHook(ABC):
    """Base class for stop hooks."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable hook name for logging."""

    @property
    def is_critical(self) -> bool:
        """If True, failure aborts remaining hooks.  Default: False."""
        return False

    @abstractmethod
    async def run(self, ctx: AgentRunContext) -> None:
        """Execute the hook."""


# ── Concrete Hooks ───────────────────────────────────────────────────────


class TranscriptPersistenceHook(StopHook):
    """Append the user↔assistant turn to the transcript store.

    This was previously a direct call in react_agent.py L475-L478.
    Moving it to a hook ensures it runs in defined order and is
    observable/retryable.
    """

    @property
    def name(self) -> str:
        return "TranscriptPersistence"

    @property
    def is_critical(self) -> bool:
        # Transcript is essential — if this fails, don't run memory hooks
        # that depend on transcript data.
        return True

    async def run(self, ctx: AgentRunContext) -> None:
        from app.services.transcript_service import transcript_service

        transcript_service.append_turn(
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            user_msg=ctx.user_message,
            ai_msg=ctx.final_answer,
        )
        logger.debug("Transcript persisted for session %s", ctx.session_id)


class MemoryExtractionHook(StopHook):
    """Run post-turn memory extraction and session compaction.

    This was previously:
      safe_background_task(
          post_turn_maintenance_service.run(session_id, user_id, ...)
      )

    Now runs inline so failures are visible and logged.  Still uses
    asyncio for I/O but no longer fire-and-forget.
    """

    @property
    def name(self) -> str:
        return "MemoryExtraction"

    async def run(self, ctx: AgentRunContext) -> None:
        from app.services.memory_extraction_service import (
            post_turn_maintenance_service,
        )

        # Agent mode always allows memory write — the agent actively
        # manages user knowledge through save_memory tool calls.
        await post_turn_maintenance_service.run(
            ctx.session_id,
            ctx.user_id,
            allow_memory_write=True,
        )
        logger.debug(
            "Memory extraction completed for session %s", ctx.session_id
        )


# ── Runner ───────────────────────────────────────────────────────────────


class StopHookRunner:
    """Orchestrates stop hooks when the agent finishes.

    Hooks run sequentially in registration order.  Each hook is
    individually guarded — a failing non-critical hook logs the error
    and allows subsequent hooks to run.

    Critical hooks (``is_critical=True``) abort the remaining chain
    on failure, since downstream hooks may depend on their side effects.
    """

    def __init__(self) -> None:
        self._hooks: list[StopHook] = [
            TranscriptPersistenceHook(),
            MemoryExtractionHook(),
        ]

    async def execute(self, ctx: AgentRunContext) -> None:
        """Run all stop hooks with the given context.

        Called by the agent loop after the query loop exits (either
        normally or via budget/error).
        """
        for hook in self._hooks:
            try:
                await hook.run(ctx)
            except Exception as exc:
                if hook.is_critical:
                    logger.error(
                        "Critical stop hook '%s' failed — aborting remaining hooks: %s",
                        hook.name,
                        exc,
                    )
                    break
                logger.warning(
                    "Stop hook '%s' failed (non-critical, continuing): %s",
                    hook.name,
                    exc,
                )
