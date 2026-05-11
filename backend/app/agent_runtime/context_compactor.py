"""Backward compatibility — re-exports from ``query_loop_compactor``.

This module is DEPRECATED.  New code should import from
``app.agent_runtime.query_loop_compactor`` directly.

Kept so that existing tests can continue to ``from
app.agent_runtime.context_compactor import ContextPipeline``.
"""

from app.agent_runtime.query_loop_compactor import (  # noqa: F401
    ContextPipeline,
    QueryLoopCompactor,
)

__all__ = ["ContextPipeline", "QueryLoopCompactor"]
