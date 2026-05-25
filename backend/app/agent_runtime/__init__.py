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
  * :mod:`harness_events`      — the streaming HarnessEvent type
                                  (re-exported by ``conversation/events``)
  * :mod:`retry_utils`         — retry-on-context-too-long helper
  * :mod:`react_agent`         — :class:`AgentBudget` dataclass +
                                  SSE event formatting helpers

External callers should reach for ``app.conversation`` — the legacy
``run_react_agent`` / ``run_react_agent_stream`` shims that wrapped
``ConversationEngine`` for the retired ``/agent/react/*`` API routes
were removed in the audit cleanup. ``/chat/sse`` (mode=agent) is the
sole entry point now.
"""
