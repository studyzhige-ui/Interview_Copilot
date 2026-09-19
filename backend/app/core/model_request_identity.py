"""Canonical request identity, shared without importing execution state."""

import hashlib
import json


def request_fingerprint(
    *,
    messages: list[dict],
    tools: list[dict] | None,
    system: str = "",
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    encoded = json.dumps(
        {
            "messages": messages,
            "tools": tools or [],
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
