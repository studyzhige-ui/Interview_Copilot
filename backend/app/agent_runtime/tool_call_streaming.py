"""Streaming tool-call accumulators for the L2 ReAct loop.

When the LLM responds with streaming chunks, tool-call payloads arrive
piece by piece (id, name, then argument fragments).  These accumulator
dataclasses collect the fragments and expose a duck-typed surface that
matches OpenAI's ``ChoiceMessage.tool_calls[i]``, so downstream
helpers like ``_tool_call_payload()`` / ``_args_summary()`` work
without conditional branches.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


class ToolCallProtocolError(ValueError):
    """An incomplete or ambiguous provider batch must never reach a handler."""


class ToolCallAssembler:
    """Accumulate a bounded batch, publish only after provider completion.

    Mirrors Codex router's completed ResponseItem boundary for transports
    that deliver separate function-call deltas instead of completed items.
    """

    def __init__(self):
        self.calls: dict[int, _ToolCallAccumulator] = {}
        self.stop_reason: str | None = None

    def feed(self, event) -> None:
        if self.stop_reason and event.tool_call_deltas:
            raise ToolCallProtocolError("tool delta arrived after completion")
        if event.stop_reason:
            if self.stop_reason and self.stop_reason != event.stop_reason:
                raise ToolCallProtocolError("conflicting model completion markers")
            self.stop_reason = event.stop_reason
        for delta in event.tool_call_deltas:
            if delta.index < 0 or delta.index >= 128:
                raise ToolCallProtocolError("tool call index exceeds batch limit")
            call = self.calls.setdefault(delta.index, _ToolCallAccumulator())
            for attribute, value in (("id", delta.call_id), ("name", delta.name)):
                if value:
                    previous = getattr(call, attribute)
                    if previous and previous != value:
                        raise ToolCallProtocolError(
                            "tool identity changed during streaming"
                        )
                    setattr(call, attribute, value)
            if len(call.id) > 128 or len(call.name) > 64:
                raise ToolCallProtocolError("tool identity exceeds protocol limit")
            if (
                len(call.arguments) + len(delta.arguments_delta)
                > settings.AGENT_MAX_TOOL_WIRE_ARG_CHARS
            ):
                raise ToolCallProtocolError("tool arguments exceed streaming limit")
            call.arguments += delta.arguments_delta

    def finish(self) -> list[_ToolCallAccumulator]:
        if not self.calls:
            return []
        if self.stop_reason not in {"tool_calls", "tool_use", "stop", "end_turn"}:
            raise ToolCallProtocolError(
                "tool batch did not complete; no tools were executed"
            )
        calls = [self.calls[index] for index in sorted(self.calls)]
        identities = [call.id for call in calls]
        if any(not call.id or not call.name for call in calls) or len(
            set(identities)
        ) != len(identities):
            raise ToolCallProtocolError(
                "tool batch has missing or duplicate identities"
            )
        return calls


@dataclass
class _ToolCallFunction:
    """Duck-typed function attribute for :class:`_ToolCallAccumulator`."""

    name: str = ""
    arguments: str = ""


@dataclass
class _ToolCallAccumulator:
    """Accumulates tool call deltas from streaming chunks.

    Duck-typed to match the OpenAI ``ChoiceMessage.tool_calls[i]``
    interface so ``_tool_call_payload()`` and ``_args_summary()`` work
    without changes.
    """

    id: str = ""
    name: str = ""
    arguments: str = ""

    @property
    def function(self) -> _ToolCallFunction:
        return _ToolCallFunction(name=self.name, arguments=self.arguments)


__all__ = [
    "ToolCallAssembler",
    "ToolCallProtocolError",
    "_ToolCallFunction",
    "_ToolCallAccumulator",
]
