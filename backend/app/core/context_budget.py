"""One provider-neutral request budget for assembly, Chat and Agent.

Counts the serialized message/tool envelope, including reasoning and images.
This is an estimate, not a claim to reproduce vendor tokenization. Agent usage
observations calibrate it after each successful request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.tokens import token_count
from app.core.config import settings


class ContextCapacityError(ValueError):
    """Required context cannot fit without losing task continuity."""


@dataclass(frozen=True)
class RequestBudget:
    window: int
    output: int
    safety: int

    @classmethod
    def resolve(
        cls, window: int, output: int, safety: int | None = None
    ) -> RequestBudget:
        window = max(1, int(window))
        if safety is None:
            safety = settings.RAG_CONTEXT_SAFETY_MARGIN
        return cls(
            window,
            max(1, min(int(output), window - 1)),
            min(max(0, safety), window // 10),
        )

    @property
    def input_limit(self) -> int:
        return max(0, self.window - self.output - self.safety)

    @property
    def compact_at(self) -> int:
        default = max(1, min(int(self.window * 0.90), self.input_limit * 9 // 10))
        configured = settings.CONTEXT_AUTO_COMPACT_TOKEN_LIMIT
        return min(default, configured) if configured > 0 else default

    def should_compact(self, total: int, prefix: int = 0) -> bool:
        body = (
            max(0, total - prefix)
            if settings.CONTEXT_AUTO_COMPACT_SCOPE == "body_after_prefix"
            else total
        )
        return body >= self.compact_at or total >= self.input_limit


def request_tokens(messages: list[dict], tools: list[dict] | None = None) -> int:
    payload = {
        "messages": [{k: v for k, v in m.items() if k != "_context"} for m in messages],
        "tools": sorted(
            tools or [], key=lambda t: str((t.get("function") or {}).get("name", ""))
        ),
    }
    return max(
        1,
        token_count(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        ),
    )
