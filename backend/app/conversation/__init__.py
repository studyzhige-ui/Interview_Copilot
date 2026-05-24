"""Unified conversation engine.

The single entry point for any chat turn — whether the user picked the
deterministic chat pipeline (L1) or the autonomous ReAct agent (L2).

Design mirrors Claude Code's two-tier architecture:

  ConversationEngine          ←  per-conversation lifecycle (analog
                                 of Claude Code's QueryEngine in
                                 ``src/QueryEngine.ts``)
       │
       │ owns:
       │   - session lifecycle (transcript_service.ensure_session)
       │   - v3 memory recall (universal + on-demand bodies)
       │   - context assembly (ContextAssemblyPipeline)
       │   - error humanisation + stop-hook dispatch
       │
       └─ delegates per-turn execution to one ExecutionStrategy:
            ├─ ChatPipelineStrategy  (L1 — fixed plan → retrieve → answer)
            └─ AgentLoopStrategy     (L2 — ReAct while-loop with tools)

Both strategies receive the assembled context + a HarnessEvent emitter,
yield events back, and report the final assistant blocks (Claude-Code
``BetaContentBlock`` shape) so the engine can persist a uniform
``content_blocks_json`` to chat_messages.
"""

from app.conversation.agent_strategy import AgentLoopStrategy
from app.conversation.chat_strategy import ChatPipelineStrategy
from app.conversation.engine import ConversationEngine
from app.conversation.events import HarnessEvent, HarnessEventType
from app.conversation.strategy import (
    ExecutionStrategy,
    StrategyResult,
    make_agent_strategy,
    make_chat_strategy,
)

__all__ = [
    "AgentLoopStrategy",
    "ChatPipelineStrategy",
    "ConversationEngine",
    "ExecutionStrategy",
    "HarnessEvent",
    "HarnessEventType",
    "StrategyResult",
    "make_agent_strategy",
    "make_chat_strategy",
]
