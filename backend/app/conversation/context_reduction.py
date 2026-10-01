"""Deterministic, recoverable tool projection before expensive summarization.

Only messages carrying a durable source identity can be offloaded. Decisions
live in the checkpoint message metadata, never in process-global state.
"""

import json

from app.core.config import settings
from app.core.context_budget import request_tokens
from app.core.tokens import token_count, truncate_to_tokens


def tool_message(call_id: str, content: str, turn_id: str | None) -> dict:
    message = {"role": "tool", "tool_call_id": call_id, "content": content}
    if turn_id:
        message["_context"] = {
            "kind": "tool",
            "id": f"agent_tool_call:{turn_id}:{call_id}",
            "source_turn_id": turn_id,
        }
    return message


def result_reference(message: dict, *, preview_tokens: int) -> str | None:
    metadata = message.get("_context", {})
    turn_id = metadata.get("source_turn_id")
    call_id = message.get("tool_call_id")
    if not turn_id or not call_id or metadata.get("tool_projection"):
        return None
    args = json.dumps(
        {"tool_call_id": call_id, "source_turn_id": turn_id}, ensure_ascii=False
    )
    return (
        "<tool-result-reference>\n"
        f"Read the durable result using read_file({args}), with offset/limit for paging.\n"
        "Preview only; this is not the complete result:\n"
        + truncate_to_tokens(str(message.get("content") or ""), preview_tokens)
        + "\n</tool-result-reference>"
    )


def reduce_tool_results(
    messages: list[dict], *, input_limit: int
) -> tuple[list[dict], dict]:
    """Bound each call batch, then evict older batches under cumulative pressure.

    The newest batch is exempt from age-based eviction. Read tools are exempt
    from batch projection so a requested page reaches the model at least once.
    Unrecoverable legacy/synthetic results are left to the summarizer.
    """
    result = list(messages)
    batches: list[list[int]] = []
    names: dict[int, str] = {}
    pending: dict[str, str] = {}
    batch: list[int] = []
    for index, message in enumerate(result):
        if message.get("role") != "tool":
            if batch:
                batches.append(batch)
            batch = []
            pending = {
                str(c.get("id")): str((c.get("function") or {}).get("name", ""))
                for c in message.get("tool_calls", [])
            }
        elif str(message.get("tool_call_id")) in pending:
            batch.append(index)
            names[index] = pending[str(message["tool_call_id"])]
    if batch:
        batches.append(batch)

    changed: list[str] = []
    before = request_tokens(result)

    def shrink(index: int) -> None:
        message = result[index]
        reference = result_reference(
            message, preview_tokens=max(0, settings.CONTEXT_TOOL_PREVIEW_TOKENS)
        )
        if reference is None or token_count(reference) >= token_count(
            str(message.get("content") or "")
        ):
            return
        result[index] = {
            **message,
            "content": reference,
            "_context": {**message["_context"], "tool_projection": "reference"},
        }
        changed.append(str(message["_context"]["id"]))

    def weight(indices: list[int]) -> int:
        return request_tokens([result[i] for i in indices])

    batch_limit = max(1, min(settings.CONTEXT_TOOL_BATCH_TOKENS, input_limit // 4))
    for indices in batches:
        for index in sorted(
            indices,
            key=lambda i: token_count(str(result[i].get("content") or "")),
            reverse=True,
        ):
            if weight(indices) <= batch_limit:
                break
            if names[index] not in {"read_file", "read_interaction_history"}:
                shrink(index)

    all_indices = [i for indices in batches for i in indices]
    history_limit = max(1, min(settings.CONTEXT_TOOL_HISTORY_TOKENS, input_limit // 3))
    for indices in batches[:-1]:
        for index in indices:
            if weight(all_indices) <= history_limit:
                break
            shrink(index)
    after = request_tokens(result)
    return result, {
        "status": "reduced" if changed else "unchanged",
        "projected_results": changed,
        "before_tokens": before,
        "after_tokens": after,
        "saved_tokens": max(0, before - after),
        "batch_limit": batch_limit,
        "history_limit": history_limit,
    }


def split_recent(
    messages: list[dict], *, token_limit: int
) -> tuple[list[dict], list[dict]]:
    """Select a contiguous suffix without splitting assistant call/result batches.

    Prefer whole user exchanges. For a long active turn, retain whole recent
    assistant steps instead; the active caller restores the exact task anchor.
    A previous summary belongs to the prefix to avoid retaining stale summaries.
    """
    floor = max(
        (
            i + 1
            for i, m in enumerate(messages)
            if m.get("_context", {}).get("kind") == "summary"
        ),
        default=0,
    )
    candidates = [
        i
        for i in range(max(1, floor), len(messages))
        if messages[i].get("role") == "assistant"
        or (
            messages[i].get("role") == "user"
            and messages[i].get("_context", {}).get("kind", "user") == "user"
        )
    ]
    fitting = []
    for i in reversed(candidates):
        if request_tokens(messages[i:]) > token_limit:
            break
        fitting.append(i)
    if not fitting:
        return messages, []
    user_starts = [i for i in fitting if messages[i].get("role") == "user"]
    start = min(user_starts or fitting)
    return messages[:start], messages[start:]
