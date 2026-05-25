"""Structured event types for the Agent Harness execution pipeline.

These events are emitted during ``run_react_agent`` and can be
serialized to JSON for SSE streaming to the frontend.
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HarnessEventType(str, Enum):
    STATUS = "status"
    TOOL_START = "tool_start"
    TOOL_DONE = "tool_done"
    TEXT = "text"
    TEXT_DELTA = "text_delta"
    BUDGET = "budget"
    ERROR = "error"
    DONE = "done"


@dataclass
class HarnessEvent:
    type: HarnessEventType
    data: dict[str, Any] = field(default_factory=dict)
    step: int = 0
    elapsed_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    # -- convenience constructors ----------------------------------------

    @classmethod
    def status(cls, message: str, *, step: int = 0, elapsed_ms: float = 0.0) -> "HarnessEvent":
        return cls(type=HarnessEventType.STATUS, data={"message": message}, step=step, elapsed_ms=elapsed_ms)

    @classmethod
    def tool_start(
        cls,
        name: str,
        args_summary: str,
        *,
        step: int,
        elapsed_ms: float,
        tool_call_id: str = "",
    ) -> "HarnessEvent":
        """``tool_call_id`` is the LLM-assigned id (``tc.id`` from the
        OpenAI tool_calls stream). Pairs with the matching ``tool_done``
        event AND with the persisted ``tool_use_block.id`` — without
        this the frontend has no choice but to pair live-stream
        tool_use/tool_result blocks by FIFO order, which breaks if a
        future agent runs tools in parallel.
        """
        return cls(
            type=HarnessEventType.TOOL_START,
            data={
                "tool": name,
                "tool_call_id": tool_call_id,
                "args_summary": args_summary,
            },
            step=step,
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def tool_done(
        cls,
        name: str,
        result_summary: str,
        *,
        step: int,
        elapsed_ms: float,
        tool_latency_ms: float,
        is_error: bool = False,
        result_content: str = "",
        tool_call_id: str = "",
    ) -> "HarnessEvent":
        """Emitted when a tool call returns.

        ``result_content`` carries the FULL LLM-visible result text —
        the frontend renders this in the expanded tool card. Pre-fix
        the event only carried ``result_summary``, so the live UI
        showed "(刷新会话以加载完整输出)" until the user reloaded;
        now the content is inline. Already bounded by the per-tool
        ``max_result_chars`` limit so SSE frame size stays sane.

        ``tool_call_id`` mirrors the matching ``tool_start`` so the
        frontend can pair live-stream tool_use/tool_result blocks by
        id rather than FIFO order.
        """
        return cls(
            type=HarnessEventType.TOOL_DONE,
            data={
                "tool": name,
                "tool_call_id": tool_call_id,
                "result_summary": result_summary,
                "result_content": result_content,
                "tool_latency_ms": round(tool_latency_ms, 2),
                "is_error": is_error,
            },
            step=step,
            elapsed_ms=elapsed_ms,
        )

    @classmethod
    def text(cls, content: str, *, step: int, elapsed_ms: float) -> "HarnessEvent":
        return cls(type=HarnessEventType.TEXT, data={"content": content}, step=step, elapsed_ms=elapsed_ms)

    @classmethod
    def text_delta(cls, delta: str, *, step: int, elapsed_ms: float) -> "HarnessEvent":
        """Incremental text chunk from streaming LLM response."""
        return cls(type=HarnessEventType.TEXT_DELTA, data={"delta": delta}, step=step, elapsed_ms=elapsed_ms)

    @classmethod
    def budget(cls, info: dict[str, Any], *, step: int, elapsed_ms: float) -> "HarnessEvent":
        return cls(type=HarnessEventType.BUDGET, data=info, step=step, elapsed_ms=elapsed_ms)

    @classmethod
    def error(cls, message: str, *, step: int = 0, elapsed_ms: float = 0.0) -> "HarnessEvent":
        return cls(type=HarnessEventType.ERROR, data={"error": message}, step=step, elapsed_ms=elapsed_ms)

    @classmethod
    def done(cls, *, step: int, elapsed_ms: float) -> "HarnessEvent":
        return cls(type=HarnessEventType.DONE, step=step, elapsed_ms=elapsed_ms)

    # -- serialization ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "step": self.step,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
