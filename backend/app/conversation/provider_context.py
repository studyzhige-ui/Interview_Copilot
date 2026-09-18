"""Canonical Context Assembly projection for message-based providers.

Chat and Agent both receive the same :class:`AssembledContext`.  This module
performs the one transport projection from that context into the provider-
neutral ``system`` + chronological ``messages`` partitions.  Vendor adapters
may change the wire shape, but they must not rebuild or reinterpret context.
"""

from __future__ import annotations

import json
import logging
import hashlib
from dataclasses import dataclass
from typing import Any

from app.core.context_budget import ContextCapacityError, request_tokens
from app.core.context_messages import normalize_tool_pairs
from app.conversation.context_window import admit, item, kind
from app.core.tokens import token_count
from app.rag.grounding.builder import grounding_builder

from app.services.chat.context_assembly_pipeline import AssembledContext, PromptRenderer
from app.services.chat.context_assembly_pipeline import render_historical_user_content
from app.services.chat.context_assembly_pipeline import SLOT_ORDER


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
                item(
                    {"role": "user", "content": render_historical_user_content(turn)},
                    "user",
                    identity=f"message:{turn.get('seq', 0)}",
                )
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
    return normalize_tool_pairs(messages)


def _project_context(
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
    if assembled.window_messages is not None:
        messages.extend(assembled.window_messages)
    elif assembled.summary:
        messages.append(
            {
                "role": "user",
                "content": (
                    "[Context Summary]\n"
                    "The following is a lossy projection of earlier messages; "
                    "exact facts must be read from their owner or History.\n\n"
                    + (
                        f"Conversation={assembled.conversation_id}; through_seq={assembled.summary_cursor}.\n"
                        if assembled.conversation_id
                        else ""
                    )
                    + assembled.summary
                ),
            }
        )
    if assembled.window_messages is None:
        messages.extend(reconstruct_history_messages(assembled.recent_turns))
    for name, tag, _ in SLOT_ORDER:
        if name in {"system_prompt", "summary", "recent_turns", "current_input"}:
            continue
        content = str(getattr(assembled, name) or "").strip()
        if content:
            messages.append(
                item({"role": "user", "content": f"{tag}\n{content}"}, name)
            )
    messages.append(
        item(
            {"role": "user", "content": assembled.current_input},
            "user",
            identity=f"turn:{assembled.turn_id or 'current'}",
        )
    )
    return ProviderContextProjection(system=system, messages=admit(messages))


def compose_provider_context(
    assembled: AssembledContext,
    *,
    renderer: PromptRenderer,
    system_prompt: str,
    tool_schemas: list[dict] | None = None,
    prompt_limit: int | None = None,
) -> ProviderContextProjection:
    """Compile and admit the actual message/tool envelope before dispatch.

    Optional evidence is reduced before history. History and the continuation
    summary must never silently disappear when summarization fails. Structured
    slots are admitted whole; references must not be cut inside a JSON object.
    """
    limit = assembled.prompt_token_limit if prompt_limit is None else prompt_limit
    omitted: list[str] = list(assembled.context_report.get("omitted", []))

    def measure() -> tuple[ProviderContextProjection, int]:
        projection = _project_context(
            assembled,
            renderer=renderer,
            system_prompt=system_prompt,
        )
        return projection, request_tokens(
            projection.with_leading_system_message(), tool_schemas
        )

    projection, total = measure()
    before = total
    if limit and total > limit and assembled.memory_block:
        assembled.memory_block = ""
        omitted.append("memory_block")
        projection, total = measure()
    if limit and total > limit and assembled.retrieval_result is not None:
        target = max(0, assembled.grounding.token_count - (total - limit) - 64)
        bundle = grounding_builder.build(
            assembled.retrieval_result, token_budget=target
        )
        assembled.grounding = bundle
        assembled.retrieved_context = bundle.context_text
        assembled.sources = bundle.sources
        omitted.append("retrieved_context:reduced")
        projection, total = measure()
    for field_name in ("memory_block", "debrief_reference", "retrieved_context"):
        if not limit or total <= limit:
            break
        if getattr(assembled, field_name):
            setattr(assembled, field_name, "")
            if field_name == "retrieved_context":
                from app.rag.domain.models import GroundingBundle

                assembled.grounding = GroundingBundle()
                assembled.sources = []
            omitted.append(field_name)
            projection, total = measure()

    def section_text(name: str) -> str:
        value = getattr(assembled, name)
        return (
            json.dumps(value, ensure_ascii=False, sort_keys=True)
            if isinstance(value, list)
            else str(value)
        )

    assembled.context_report = {
        **assembled.context_report,
        "estimated_request_tokens": total,
        "before_tokens": before,
        "input_limit": limit,
        "output_reserve": assembled.output_token_reserve,
        "tool_count": len(tool_schemas or []),
        "omitted": omitted,
        "history_messages": len(assembled.window_messages)
        if assembled.window_messages is not None
        else len(assembled.recent_turns),
        "summary_present": any(
            kind(m) == "summary" for m in assembled.window_messages or []
        )
        or bool(assembled.summary),
        "summary_cursor": assembled.summary_cursor,
        "compiler_version": "codex-replacement-history-v1",
        "checkpoint_version": assembled.checkpoint_version,
        "sections": [
            {
                "slot": name,
                "estimated_tokens": token_count(section_text(name)),
                "content_hash": hashlib.sha256(section_text(name).encode()).hexdigest(),
                "state": "lossy"
                if name == "summary"
                else "bounded"
                if name == "retrieved_context"
                else "complete",
            }
            for name, _, custom in SLOT_ORDER
            if getattr(assembled, name)
        ],
        "tool_names": sorted(
            str((tool.get("function") or {}).get("name") or "")
            for tool in tool_schemas or []
        ),
        "source_refs": [source.get("ref") for source in assembled.sources],
        "system_prefix_hash": hashlib.sha256(projection.system.encode()).hexdigest(),
    }
    logging.getLogger(__name__).info("Context admission %s", assembled.context_report)
    if limit and total > limit:
        raise ContextCapacityError(
            "当前对话的必要上下文超出模型窗口，已保留原始历史。"
            "请缩小本次输入或选择更大上下文的模型后重试。"
        )
    assembled.total_tokens = total
    return projection


__all__ = [
    "ProviderContextProjection",
    "compose_provider_context",
    "reconstruct_history_messages",
]
