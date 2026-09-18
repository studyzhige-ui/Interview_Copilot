"""Shared dispatch lifecycle for Chat and Agent, including durable compaction."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from app.core.context_budget import ContextCapacityError, RequestBudget, request_tokens
from app.conversation import context_store
from app.conversation.context_window import compact, admit, kind


async def prepare(
    assembled,
    *,
    renderer,
    system_prompt,
    client,
    profile,
    tool_schemas=None,
    force=False,
):
    from app.conversation.provider_context import (
        _project_context,
        compose_provider_context,
    )

    candidate = _project_context(
        assembled, renderer=renderer, system_prompt=system_prompt
    )
    budget = RequestBudget.resolve(
        profile.context_window, assembled.output_token_reserve
    )
    history = assembled.window_messages
    prefix = request_tokens(
        [{"role": "system", "content": candidate.system}], tool_schemas
    )
    if history and (
        force
        or budget.should_compact(
            request_tokens(candidate.with_leading_system_message(), tool_schemas),
            prefix,
        )
    ):
        replaced, report = await compact(
            [{"role": "system", "content": candidate.system}, *history],
            client=client,
            profile=profile,
            output_tokens=assembled.output_token_reserve,
        )
        replacement = [m for m in replaced if m.get("role") != "system"]
        # Publish only after the checkpoint is durable and fenced.
        saved = await asyncio.to_thread(
            context_store.save,
            assembled.conversation_id,
            expected_version=assembled.checkpoint_version,
            through_seq=assembled.through_seq,
            state={"messages": replacement, "compaction": report},
            turn_id=assembled.turn_id,
            dispatch_generation=assembled.dispatch_generation,
            replace=True,
        )
        if not saved:
            raise ContextCapacityError(
                "上下文已被另一执行更新，请重试；原始历史仍然保留。"
            )
        assembled.window_messages = replacement
        assembled.checkpoint_version = saved["version"]
        assembled.context_report["compaction"] = report
    return compose_provider_context(
        assembled,
        renderer=renderer,
        system_prompt=system_prompt,
        tool_schemas=tool_schemas,
    )


async def finish(assembled, *, messages: list[dict], through_seq: int):
    """Commit final projection after the raw transcript has been written.

    If a process dies between these writes, the next load replays raw tail;
    it can expand the projection, but cannot lose a user/assistant message.
    """
    canonical = deepcopy([m for m in messages if m.get("role") != "system"])
    for message in canonical:
        message.pop("reasoning_content", None)
    saved = await asyncio.to_thread(
        context_store.save,
        assembled.conversation_id,
        expected_version=assembled.checkpoint_version,
        through_seq=through_seq,
        state={
            "messages": admit(canonical),
            "compaction": assembled.context_report.get("compaction", {}),
        },
        turn_id=assembled.turn_id,
        dispatch_generation=assembled.dispatch_generation,
    )
    if saved:
        assembled.checkpoint_version = saved["version"]


def latest_summary(messages: list[dict]) -> str:
    return next(
        (
            str(m.get("content") or "")
            for m in reversed(messages)
            if kind(m) == "summary"
        ),
        "",
    )
