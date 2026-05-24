"""Unified event protocol for streaming.

Used by both chat (L1) and agent (L2) strategies so the frontend
consumes one wire format. Re-exports the existing
:class:`app.agent_runtime.harness_events.HarnessEvent` to keep types
identical without duplicating the class definition.

L1 (chat) emits a subset:        status / text_delta / text / error / done
L2 (agent) adds:                 + tool_start / tool_done / budget

The frontend's chat renderer treats unknown event types as no-ops, so
keeping L1 to the subset is forward-compatible with the L2 fields.
"""
from app.agent_runtime.harness_events import HarnessEvent, HarnessEventType

__all__ = ["HarnessEvent", "HarnessEventType"]
