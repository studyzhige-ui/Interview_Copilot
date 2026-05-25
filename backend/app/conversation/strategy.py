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
from typing import Any, AsyncGenerator, Protocol, runtime_checkable

from app.conversation.events import HarnessEvent


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

    # Prepared context — the FULL ``AssembledContext`` built by the
    # engine. Strategies should render via
    # ``prompt_renderer.render_answer_prompt(ctx.assembled, ...)``
    # so memory, debrief reference, and RAG all reach the LLM with
    # the SLOT_ORDER contract intact. Engine sets this in _prepare.
    assembled: Any = None              # AssembledContext (forward ref to avoid import cycle)
    knowledge_chunks: list[dict] = field(default_factory=list)
    v3_memory_block: str = ""          # Convenience: already-rendered v3 memory bundle
    rewritten_query: str | None = None
    needs_knowledge_retrieval: bool = False

    # Global memory toggle resolved ONCE by the engine in ``_prepare``.
    # The agent strategy uses this to gate the recall_memory /
    # save_memory tools out of the manifest. Pre-fix the engine read
    # this in _prepare AND the strategy re-read the same value in its
    # execute(), opening 2 DB sessions for a single boolean.
    # Engine populates; strategy reads only.
    global_memory_on: bool = False

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
    tool_calls: int = 0
    steps_used: int = 0
    stop_reason: str | None = None

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


# ── Concrete strategies (implementations live in their own modules) ──
# The factory functions below are populated in G3/G4 once the
# concrete classes land. Keeping the imports lazy avoids a circular
# import via conversation/engine.py → strategy.py → agent_runtime/…


def make_agent_strategy() -> ExecutionStrategy:
    """Factory for the L2 ReAct strategy. Lazy-imported so the chat
    path doesn't pay the agent_runtime import cost when running pure-
    chat traffic."""
    from app.conversation.agent_strategy import AgentLoopStrategy
    return AgentLoopStrategy()


def make_chat_strategy() -> ExecutionStrategy:
    """Factory for the L1 chat-pipeline strategy."""
    from app.conversation.chat_strategy import ChatPipelineStrategy
    return ChatPipelineStrategy()


# Concrete classes live in agent_strategy.py / chat_strategy.py and
# are re-exported via app.conversation.__init__ for callers who want
# the class itself (e.g. tests, type hints). No __getattr__ magic
# here — the package __init__ does the re-export eagerly anyway, so
# lazy module-level lookup added zero value.


__all__ = [
    "ExecutionStrategy",
    "StrategyContext",
    "StrategyResult",
    "make_agent_strategy",
    "make_chat_strategy",
]
