"""Model-visible history, derived from Codex 83dc7d11 (Apache-2.0).

Raw transcripts and business state remain authoritative. This module owns only
the replaceable model projection; contextual user-role messages are not intent.
See third_party/codex-context for the unmodified compaction templates/license.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from app.core.context_budget import ContextCapacityError, RequestBudget, request_tokens
from app.core.context_messages import normalize_tool_pairs
from app.core.tokens import token_count, truncate_to_tokens
from app.core.config import settings

UPSTREAM_REVISION = "83dc7d11e873f43533dc898d50fae71cf4d55dc5"
# Source distributions and Docker both carry these files beside the package.
_TEMPLATES = Path(__file__).with_name("context_templates")
COMPACT_PROMPT = (_TEMPLATES / "prompt.md").read_text(encoding="utf-8").strip()
SUMMARY_PREFIX = (_TEMPLATES / "summary_prefix.md").read_text(encoding="utf-8").strip()
USER_RETAIN_TOKENS = 20_000
TOOL_OUTPUT_TOKENS = 10_000


def item(message: dict, kind: str, *, identity: str | None = None, **metadata) -> dict:
    return {
        **deepcopy(message),
        "_context": {"kind": kind, "id": identity or str(uuid4()), **metadata},
    }


def wire(messages: list[dict]) -> list[dict]:
    return [
        {k: v for k, v in message.items() if k != "_context"} for message in messages
    ]


def kind(message: dict) -> str:
    return message.get("_context", {}).get("kind", message.get("role", "unknown"))


def admit(messages: list[dict], *, tool_limit: int | None = None) -> list[dict]:
    """Bound every tool output on admission; never modify the durable result.

    Unlike the former pressure whitelist this also applies to newly read tools.
    Prefix/suffix are explicitly excerpts, not a valid structured object.
    """
    tool_limit = max(
        1,
        int(
            tool_limit
            if tool_limit is not None
            else settings.CONTEXT_TOOL_OUTPUT_TOKENS
        ),
    )
    result = []
    for message in messages:
        if message.get("role") == "tool" and isinstance(message.get("content"), str):
            content = message["content"]
            if token_count(content) > tool_limit:
                marker = (
                    "\n[Tool output truncated; excerpts only. Read the durable result "
                    f"by call_id={message.get('tool_call_id', '')} for omitted data.]\n"
                )
                room = max(0, tool_limit - token_count(marker))
                head = truncate_to_tokens(content, room // 2)
                # Select a token-bounded suffix without reversing Unicode graphemes.
                lo, hi = 0, len(content)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if token_count(content[mid:]) > room - room // 2:
                        lo = mid + 1
                    else:
                        hi = mid
                suffix = content[lo:]
                # Token counts are not additive at concatenation boundaries.
                # Keep the tail and explicit excerpt marker, shrinking the
                # disposable prefix first; tiny budgets still stay bounded.
                projected = head + marker + suffix
                while head and token_count(projected) > tool_limit:
                    head = head[: max(0, len(head) - max(1, len(head) // 100))]
                    projected = head + marker + suffix
                if token_count(projected) > tool_limit:
                    projected = truncate_to_tokens(marker, tool_limit)
                message = {**message, "content": projected}
        result.append(
            message
            if "_context" in message
            else item(message, message.get("role", "unknown"))
        )
    return result


def remove_oldest_group(messages: list[dict]) -> list[dict]:
    """Remove the oldest item and any corresponding function call/result pair."""
    if not messages:
        return []
    first, *rest = messages
    call_ids = {str(call.get("id")) for call in first.get("tool_calls", [])}
    if first.get("role") == "tool":
        call_ids.add(str(first.get("tool_call_id")))
    output = []
    for message in rest:
        if (
            message.get("role") == "tool"
            and str(message.get("tool_call_id")) in call_ids
        ):
            continue
        calls = message.get("tool_calls")
        if calls and any(str(call.get("id")) in call_ids for call in calls):
            message = {
                **message,
                "tool_calls": [
                    call for call in calls if str(call.get("id")) not in call_ids
                ],
            }
        output.append(message)
    return output


def replacement_history(
    messages: list[dict], summary: str, *, user_limit: int = USER_RETAIN_TOKENS
) -> list[dict]:
    """Codex local-compaction shape: recent real users, then handoff summary."""
    users, remaining = [], user_limit
    for message in reversed(messages):
        if kind(message) != "user" or message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        if not remaining:
            break
        clipped = truncate_to_tokens(content, remaining)
        users.append({**message, "content": clipped})
        remaining -= token_count(clipped)
    users.reverse()
    users.append(
        item({"role": "user", "content": SUMMARY_PREFIX + "\n\n" + summary}, "summary")
    )
    return users


async def compact(
    messages: list[dict], *, client, profile, output_tokens: int = 4096
) -> tuple[list[dict], dict]:
    """Same selected model, original prompt, no JSON schema or worker model.

    Only a completed response replaces history. Overflow trims a temporary
    summarizer input at paired item boundaries; failures preserve live history.
    """
    import asyncio
    from app.core.model_provider_adapter import (
        ModelProviderAdapter,
        build_provider_request,
    )

    systems = [m for m in messages if m.get("role") == "system"]
    original = [m for m in messages if m.get("role") != "system"]
    source = admit(original)
    output = min(output_tokens, int(profile.max_output_tokens or output_tokens))
    budget = RequestBudget.resolve(profile.context_window, output)
    prompt = {"role": "user", "content": COMPACT_PROMPT}
    removed = 0
    while source:
        request_messages = [*systems, *normalize_tool_pairs(source), prompt]
        if request_tokens(wire(request_messages)) > budget.input_limit:
            source = remove_oldest_group(source)
            removed += 1
            continue
        request = build_provider_request(
            messages=wire(request_messages),
            tools=None,
            max_tokens=output,
            temperature=0.2,
        )
        try:
            async with asyncio.timeout(120):
                stream = await ModelProviderAdapter(
                    client=client, profile=profile
                ).start_stream(request)
                text, stop, usage = [], None, None
                async for event in stream:
                    text.append(event.text_delta)
                    stop = event.stop_reason or stop
                    usage = event.usage or usage
            summary = "".join(text).strip()
            if not summary or stop not in {"stop", "end_turn"}:
                raise ContextCapacityError("压缩未完整结束，原上下文已保留。")
            retained_limit = min(
                USER_RETAIN_TOKENS,
                max(
                    0,
                    budget.input_limit
                    - request_tokens(systems)
                    - token_count(summary)
                    - 512,
                ),
            )
            replacement = replacement_history(
                original, summary, user_limit=retained_limit
            )
            return [*systems, *replacement], {
                "status": "completed",
                "source_revision": UPSTREAM_REVISION,
                "summary_tokens": token_count(summary),
                "trimmed_input_groups": removed,
                "model": profile.model,
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
            }
        except Exception as exc:
            # Provider overflow is distinct from auth, cancellation or transport failure.
            from app.agent_runtime.retry_utils import classify_api_error, ErrorCategory

            if (
                isinstance(exc, ContextCapacityError)
                or classify_api_error(exc) != ErrorCategory.CONTEXT_TOO_LONG
            ):
                raise
            source = remove_oldest_group(source)
            removed += 1
    raise ContextCapacityError("压缩输入无法放入模型窗口，原上下文已保留。")
