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


__all__ = ["_ToolCallFunction", "_ToolCallAccumulator"]
