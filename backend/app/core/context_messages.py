"""Chronological tool-pair normalization shared by replay and reduction."""

from __future__ import annotations
from app.core.context_wire import wire as wire


def normalize_tool_pairs(messages: list[dict]) -> list[dict]:
    """Repair interrupted calls in place in chronology, without claiming success.

    A result may only belong to the immediately preceding assistant call batch.
    Orphan, duplicate and late results cannot silently attach to another turn.
    Input dictionaries and durable history are never mutated.
    """
    normalized: list[dict] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        index += 1
        if message.get("role") == "tool":
            continue
        normalized.append(message)
        calls = (
            message.get("tool_calls") if message.get("role") == "assistant" else None
        )
        if not calls:
            continue
        expected = {str(call["id"]) for call in calls if call.get("id")}
        seen: set[str] = set()
        while index < len(messages) and messages[index].get("role") == "tool":
            result = messages[index]
            index += 1
            identity = str(result.get("tool_call_id") or "")
            if identity in expected and identity not in seen:
                normalized.append(result)
                seen.add(identity)
        for call in calls:
            identity = str(call.get("id") or "")
            if identity and identity not in seen:
                normalized.append(
                    {
                        "role": "tool",
                        "tool_call_id": identity,
                        "content": "[Result unavailable in history; execution outcome unknown. Reread the exact Tool Call record before relying on it.]",
                    }
                )
                seen.add(identity)
    return normalized
