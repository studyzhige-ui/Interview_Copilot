"""Per-turn execution strategies (L1 chat pipeline vs L2 ReAct agent).

A strategy receives a fully-prepared :class:`StrategyContext` (built by
:class:`~app.conversation.engine.ConversationEngine` during its
``_prepare`` phase) and yields :class:`HarnessEvent` over the wire.

It returns its result by populating a :class:`StrategyResult` that the
engine reads after the generator exhausts — final answer text, the
assistant content blocks to persist (Claude-Code shape), and any extra
metadata the engine wants for hooks / metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal, Protocol, runtime_checkable

from app.conversation.events import HarnessEvent

TurnOutcome = Literal["completed", "waiting", "blocked", "failed", "cancelled"]

# ── Context passed into a strategy ────────────────────────────────────


@dataclass
class StrategyContext:
    """Everything a strategy needs to do one turn.

    The engine builds this once in ``_prepare()`` and hands it to
    ``strategy.execute()``. Strategies treat it as read-only.
    """

    # Conversation identity
    user_id: str
    session_id: str
    user_message: str
    turn_id: str | None = None
    dispatch_generation: int = 1
    runtime_profile: str = "career"

    # Prepared context — the FULL ``AssembledContext`` built by the
    # engine. Strategies should render via
    # ``prompt_renderer.render_answer_prompt(ctx.assembled, ...)``
    # so memory, debrief reference, and RAG all reach the LLM with
    # the SLOT_ORDER contract intact. Engine sets this in _prepare.
    assembled: Any = None  # AssembledContext (forward ref to avoid import cycle)
    rewritten_query: str | None = None
    needs_knowledge_retrieval: bool = False

    # ── Retrieval provenance + state (L1 RAG) ─────────────────────
    retrieval_hit: bool = False

    # Per-strategy extras (e.g. agent gets a tool registry handle)
    extras: dict[str, Any] = field(default_factory=dict)


# ── Result returned by a strategy ─────────────────────────────────────


@dataclass
class StrategyResult:
    """What a strategy reports back after finishing one turn.

    ``assistant_blocks`` follows the Anthropic BetaContentBlock shape
    (``[{type: "text"|"tool_use"|"tool_result", ...}, ...]``).
    The L1 chat strategy emits a single-text-block array. The L2 agent
    strategy emits an interleaved chain so the frontend folded-card
    UX has every tool call to render on history reload.
    """

    final_answer: str = ""
    assistant_blocks: list[dict] = field(default_factory=list)

    # Optional per-turn metrics (engine forwards these to telemetry).
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    provider_id: str = ""
    prompt_cache_supported: bool = False
    prompt_cache_enabled: bool = False
    tool_calls: int = 0
    steps_used: int = 0
    stop_reason: str | None = None
    # Kernel outcome for this execution pass. ``waiting`` is deliberately
    # non-terminal: the worker is released while the same durable Turn keeps
    # ownership of its pending Interaction and original Tool Call identity.
    outcome: TurnOutcome = "completed"

    # Free-form extras (e.g. trace persistence flags for the agent strategy)
    extras: dict[str, Any] = field(default_factory=dict)


# ── Strategy protocol ─────────────────────────────────────────────────


@runtime_checkable
class ExecutionStrategy(Protocol):
    """The execution-phase plug-in for ConversationEngine.

    Implementations:
      - ChatPipelineStrategy → fixed deterministic pipeline (L1)
      - AgentLoopStrategy    → ReAct while-loop with tools (L2)
    """

    name: str  # for logging / metrics ("chat" or "agent")

    async def execute(
        self,
        ctx: StrategyContext,
        result: StrategyResult,
    ) -> AsyncGenerator[HarnessEvent, None]:
        """Run one turn. Populate ``result`` as side effects.

        Yield HarnessEvents as the turn progresses. The engine pipes
        them to the SSE client unchanged.
        """
        ...


__all__ = [
    "ExecutionStrategy",
    "StrategyContext",
    "StrategyResult",
    "TurnOutcome",
]
