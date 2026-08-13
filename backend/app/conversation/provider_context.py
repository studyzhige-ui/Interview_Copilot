"""Canonical Context Assembly projection for message-based providers.

Chat and Agent both receive the same :class:`AssembledContext`.  This module
performs the one transport projection from that context into the provider-
neutral ``system`` + chronological ``messages`` partitions.  Vendor adapters
may change the wire shape, but they must not rebuild or reinterpret context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.services.chat.context_assembly_pipeline import AssembledContext, PromptRenderer
from app.services.chat.context_assembly_pipeline import render_historical_user_content


@dataclass(frozen=True)
class ProviderContextProjection:
    """Stable system instructions and chronological model-visible messages."""

    system: str
    messages: list[dict[str, Any]]

    def with_leading_system_message(self) -> list[dict[str, Any]]:
        """Return the loop-local canonical message list.

        The Agent compactor historically keeps the system partition as a
        leading message.  Provider adapters split it back out at the final
        request boundary; keeping this helper avoids a second system string.
        """

        return [{"role": "system", "content": self.system}, *self.messages]


def reconstruct_history_messages(turns: list[dict]) -> list[dict[str, Any]]:
    """Rebuild exact chronological turns, preserving complete Tool pairs.

    Persisted Agent messages use the product's Anthropic-style block shape.
    The provider-neutral loop representation is OpenAI-like because it can
    represent assistant calls and their result identities without a vendor
    dependency.  Native adapters translate it only at the wire boundary.
    """

    messages: list[dict[str, Any]] = []
    for turn in turns:
        role = turn.get("role")
        if role == "User":
            messages.append(
                {"role": "user", "content": render_historical_user_content(turn)}
            )
            continue
        if role != "Agent":
            continue

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        def flush_assistant() -> None:
            if not text_parts and not tool_calls:
                return
            assistant: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(text_parts),
            }
            if tool_calls:
                assistant["tool_calls"] = list(tool_calls)
            messages.append(assistant)
            text_parts.clear()
            tool_calls.clear()

        blocks = turn.get("blocks") or []
        for block in blocks:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(
                                block.get("input") or {}, ensure_ascii=False
                            ),
                        },
                    }
                )
            elif block_type == "tool_result":
                # A provider assistant call must precede its result. Flush at
                # the first result so later text/tool cycles stay distinct.
                flush_assistant()
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": str(block.get("content") or ""),
                    }
                )
        flush_assistant()

        # Legacy rows may carry content without structured blocks.
        if not blocks and turn.get("content"):
            messages.append({"role": "assistant", "content": turn["content"]})
    return messages


def compose_provider_context(
    assembled: AssembledContext,
    *,
    renderer: PromptRenderer,
    system_prompt: str,
) -> ProviderContextProjection:
    """Project one assembled Turn without changing source selection.

    Summary remains labelled, lossy data; exact retained History follows in
    chronological order; per-turn typed data stays beside the admitted user
    input.  No runtime checkpoint or pending submission is accepted here.
    """

    system = renderer.render_stable_system_prompt(
        assembled,
        system_prompt=system_prompt,
    )
    messages: list[dict[str, Any]] = []
    if assembled.summary:
        messages.append(
            {
                "role": "user",
                "content": (
                    "[Context Summary]\n"
                    "The following is a lossy projection of earlier messages; "
                    "exact facts must be read from their owner or History.\n\n"
                    f"{assembled.summary}"
                ),
            }
        )
    messages.extend(reconstruct_history_messages(assembled.recent_turns))
    messages.append(
        {
            "role": "user",
            "content": renderer.render_current_user_message(assembled),
        }
    )
    return ProviderContextProjection(system=system, messages=messages)


__all__ = [
    "ProviderContextProjection",
    "compose_provider_context",
    "reconstruct_history_messages",
]
