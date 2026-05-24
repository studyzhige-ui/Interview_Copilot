"""L2 agent infrastructure — primitives used by the conversation engine.

Post-Stage-G the actual agent loop lives in
:class:`app.conversation.agent_strategy.AgentLoopStrategy`. This package
hosts the lower-layer building blocks the strategy depends on:

  * :mod:`tools/`              — registered ReAct tools (knowledge, memory,
                                  resume, web, jobs, file_io, …)
  * :mod:`tool_registry`       — self-registration + OpenAI schema export
  * :mod:`tool_call_streaming` — incremental tool_call accumulator from
                                  OpenAI streaming responses
  * :mod:`tool_result_storage` — on-disk persistence + per-turn budget
                                  for oversized tool outputs
  * :mod:`context_compactor`   — multi-layer context-window compaction
  * :mod:`agent_progress_hooks` / :mod:`agent_stop_hooks` — pluggable
                                  hooks fired during / after a turn
  * :mod:`harness_events`      — the streaming HarnessEvent type
                                  (re-exported by ``conversation/events``)
  * :mod:`retry_utils`         — retry-on-context-too-long helper
  * :mod:`react_agent`         — :class:`AgentBudget` dataclass +
                                  ``run_react_agent[_stream]`` shims
                                  that delegate to
                                  :class:`app.conversation.ConversationEngine`

External callers should reach for ``app.conversation`` first —
``run_react_agent[_stream]`` is the only public symbol here that's
worth importing directly (kept for backward compatibility with the
``/agent/react/*`` API routes).
"""
from app.agent_runtime.react_agent import run_react_agent, run_react_agent_stream

__all__ = ["run_react_agent", "run_react_agent_stream"]
