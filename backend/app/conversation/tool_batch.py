"""Preflight, schedule and project one model-issued tool batch.

Durable individual-call execution remains in tool_call_executor.
"""

from __future__ import annotations
from dataclasses import replace
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator
from app.agent_runtime.react_agent import (
    AgentRunState,
    _args_summary,
    _result_summary,
    _tool_call_payload,
)
from app.agent_runtime.tool_call_executor import (
    ToolExecutionPlan,
    defer_tool_calls,
    execute_tool_call,
    plan_tool_call,
    persist_turn_budget,
)
from app.agent_runtime.tool_policy import ToolEffect, ToolPolicyContext
from app.agent_runtime.tool_call_streaming import _ToolCallAccumulator
from app.agent_runtime.tool_registry import AgentToolContext
from app.agent_runtime.tool_registry import ToolDispatchPlan
from app.agent_runtime.tool_registry import parse_tool_arguments
from app.agent_runtime.builtin_tools import registry
from app.agent_runtime.tool_registry import safe_json_dumps
from app.agent_runtime.tool_redaction import redact_tool_value
from app.agent_runtime.turn_tool_catalog import TurnToolCatalog
from app.conversation.events import HarnessEvent
from app.conversation.strategy import StrategyContext
from app.core.config import settings

from app.agent_runtime.tool_registry import ToolRegistry
from app.core.context_messages import runtime_control_message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PreparedToolCall:
    model_index: int
    call: _ToolCallAccumulator
    dispatch_plan: ToolDispatchPlan
    execution_plan: ToolExecutionPlan
    context: AgentToolContext


_REPEAT_NUDGE_SOFT = 3
_REPEAT_NUDGE_FIRM = 6


def _repeat_call_nudge(tool_name: str, count: int) -> str:
    """Soft-steer message when a tool is re-called with identical arguments."""
    base = (
        f"Note: `{tool_name}` has now been called {count} times with identical "
        f"arguments — repeating it rarely yields new information."
    )
    if count >= _REPEAT_NUDGE_FIRM:
        return (
            base + " Stop repeating it: change the arguments, try a different "
            "tool, or give your final answer based on what you already have."
        )
    return (
        base + " Consider changing the arguments, trying a different tool, or "
        "answering with what you have."
    )


async def _prepare_call(
    model_index: int,
    tc: _ToolCallAccumulator,
    *,
    ctx: StrategyContext,
    budget: AgentRunState,
    dispatcher: TurnToolCatalog | ToolRegistry,
    user_pk: int | None,
    duplicate_call_ids: set[str],
) -> _PreparedToolCall:
    parse_error: dict[str, Any] | None = None
    try:
        parsed_args = parse_tool_arguments(tc.arguments)
    except Exception:
        parsed_args = {}
        parse_error = {
            "error": "tool_args_parse_failed",
            "tool_name": tc.name,
        }

    tool_ctx = AgentToolContext(
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        user_pk=user_pk,
        tool_call_id=tc.id,
    )
    dispatch_plan = await dispatcher.plan_call(tc.name, parsed_args, tool_ctx)
    concrete_error = parse_error or dispatch_plan.error
    if tc.id in duplicate_call_ids or len(tc.id) > 128:
        concrete_error = {
            "error": "tool_call_identity_conflict",
            "tool_name": tc.name,
        }
    if concrete_error is not dispatch_plan.error:
        dispatch_plan = replace(
            dispatch_plan,
            concurrency_safe=False,
            error=concrete_error,
        )

    try:
        task_authorized, reversible = dispatcher.policy_traits(
            tc.name, dispatch_plan.arguments, tool_ctx, ctx.user_message
        )
    except Exception:  # noqa: BLE001 - a broken predicate denies execution
        task_authorized, reversible = False, False
        dispatch_plan = replace(
            dispatch_plan,
            concurrency_safe=False,
            error={"error": "tool_preflight_failed", "tool_name": tc.name},
        )

    policy_context = ToolPolicyContext(
        execution_mode=str(ctx.extras.get("execution_mode", "standard")),
        connection_ready=dispatch_plan.connection_ready,
        provider_scope_allows=dispatch_plan.provider_scope_allows,
        current_task_authorizes=task_authorized,
        user_confirmed_this_call=bool(
            ctx.extras.get("confirmed_tool_call_id") == tc.id
        ),
        reversible=reversible,
        hard_deny_reason=dispatch_plan.hard_deny_reason,
        user_retained_decision=bool(ctx.extras.get("user_retained_tool_decision")),
    )
    execution_plan = await plan_tool_call(
        call_id=tc.id,
        turn_id=ctx.turn_id,
        tool_name=tc.name,
        arguments=dispatch_plan.arguments,
        effect=dispatch_plan.effect,
        policy_context=policy_context,
        dispatch_generation=ctx.dispatch_generation,
        resume_waiting=bool(
            ctx.extras.get("resume_tool_call_id") == tc.id
            or tc.id in set(ctx.extras.get("resume_tool_call_ids") or ())
            or tc.id in set(ctx.extras.get("batch_reserved_tool_call_ids") or ())
        ),
        preflight_error=dispatch_plan.error,
        model_step=budget.steps,
        model_call_index=model_index,
        model_call_order=(
            (ctx.dispatch_generation - 1) * 1_000_000
            + budget.steps * 10_000
            + model_index
        ),
        handler_identity=dispatch_plan.handler_identity,
        provider_identity=dispatch_plan.provider_identity,
        connection_identity=dispatch_plan.connection_identity,
        resource_identities=dispatch_plan.resource_identities,
        receipt_ref_resolver=dispatch_plan.receipt_ref_resolver,
        max_argument_chars=dispatch_plan.max_argument_chars,
    )
    return _PreparedToolCall(
        model_index=model_index,
        call=tc,
        dispatch_plan=dispatch_plan,
        execution_plan=execution_plan,
        context=tool_ctx,
    )


async def _run_tool(
    prepared_call: _PreparedToolCall,
    tool_started: float,
    *,
    ctx: StrategyContext,
    dispatcher: TurnToolCatalog | ToolRegistry,
    user_pk: int,
) -> tuple[dict[str, Any], str, float]:
    tc = prepared_call.call
    tool_name = tc.name
    dispatch_plan = prepared_call.dispatch_plan
    parsed_args = dispatch_plan.arguments
    tool_ctx = prepared_call.context

    async def dispatch() -> dict[str, Any]:
        if tool_name not in dispatcher:
            return {"error": "unknown_tool", "tool_name": tool_name}
        return await dispatcher.dispatch(tool_name, parsed_args, tool_ctx)

    observation = await execute_tool_call(
        call_id=tc.id,
        turn_id=ctx.turn_id,
        session_id=ctx.session_id,
        user_id=user_pk,
        tool_name=tool_name,
        arguments=parsed_args,
        timeout_seconds=settings.AGENT_TOOL_TIMEOUT_SECONDS,
        dispatch=dispatch,
        effect=dispatch_plan.effect,
        dispatch_generation=ctx.dispatch_generation,
        resume_waiting=bool(
            ctx.extras.get("resume_tool_call_id") == tc.id
            or tc.id in set(ctx.extras.get("resume_tool_call_ids") or ())
            or tc.id in set(ctx.extras.get("batch_reserved_tool_call_ids") or ())
        ),
        plan=prepared_call.execution_plan,
        preflight_error=dispatch_plan.error,
    )
    latency_ms = round((time.perf_counter() - tool_started) * 1000, 2)
    # AgentToolCall already owns the full redacted result. Keep only a
    # bounded pointer in model context; read_file can page the same
    # canonical row on any worker after retry or restart.
    result_text = safe_json_dumps(redact_tool_value(observation))
    return observation, result_text, latency_ms


def _can_run_in_parallel(prepared_call: _PreparedToolCall) -> bool:
    plan = prepared_call.dispatch_plan
    return bool(
        plan.error is None
        and plan.handler_exists
        and plan.effect is ToolEffect.READ
        and plan.concurrency_safe
        # A connection/approval ask remains in the candidate read
        # batch so its preflight can stop every untouched sibling.
        # Hard denies and mutating/unknown effects split the batch.
        and prepared_call.execution_plan.decision.outcome != "deny"
        and prepared_call.execution_plan.existing_result is None
    )


async def execute_tool_batch(
    *,
    ctx: StrategyContext,
    messages: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    tool_calls_acc: list[_ToolCallAccumulator],
    assistant_content: str,
    reasoning_content: str,
    budget: AgentRunState,
    tool_catalog: TurnToolCatalog | None = None,
) -> AsyncGenerator[HarnessEvent, None]:
    # ``reasoning_content`` (thinking-mode trace) MUST round-trip
    # back to the API on the next assistant message — otherwise
    # DeepSeek V4 Flash / o1-style models reject the next call with
    # HTTP 400 "The reasoning_content in the thinking mode must be
    # passed back to the API". We attach it conditionally so plain
    # (non-thinking) models that never produce reasoning_content
    # don't get a confusing empty field.
    call_id_counts: dict[str, int] = {}
    for tool_call in tool_calls_acc:
        # Preserve every provider-issued identity, including a replay from
        # a later model step.  Only a genuinely missing id is synthesized.
        if not tool_call.id:
            tool_call.id = f"call_{uuid.uuid4().hex}"
        call_id_counts[tool_call.id] = call_id_counts.get(tool_call.id, 0) + 1
        budget.tool_call_ids.add(tool_call.id)
    duplicate_call_ids = {
        call_id for call_id, count in call_id_counts.items() if count > 1
    }

    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": assistant_content,
        "tool_calls": [_tool_call_payload(c) for c in tool_calls_acc],
    }
    if reasoning_content:
        assistant_msg["reasoning_content"] = reasoning_content
    messages.append(assistant_msg)

    nudge_repeat = 0
    nudge_tool = ""
    replan_message = ""
    dispatcher = tool_catalog or registry

    # Whole-response concrete preflight happens before the first handler.
    # This validates every candidate input and freezes Policy/resource facts
    # used to partition safe batches; it performs no Provider operation.
    prepared_calls = [
        await _prepare_call(
            index,
            tc,
            ctx=ctx,
            budget=budget,
            dispatcher=dispatcher,
            user_pk=tool_catalog.user_pk if tool_catalog else None,
            duplicate_call_ids=duplicate_call_ids,
        )
        for index, tc in enumerate(tool_calls_acc)
    ]

    call_index = 0
    while call_index < len(prepared_calls):
        # Partition by concrete input/effect/resource facts. Mutating and
        # unknown-effect calls always form an exclusive one-item batch.
        batch_end = call_index + 1
        occupied_resources = set(
            prepared_calls[call_index].dispatch_plan.resource_identities
        )
        if _can_run_in_parallel(prepared_calls[call_index]):
            while batch_end < len(prepared_calls) and _can_run_in_parallel(
                prepared_calls[batch_end]
            ):
                candidate_resources = set(
                    prepared_calls[batch_end].dispatch_plan.resource_identities
                )
                if occupied_resources.intersection(candidate_resources):
                    break
                occupied_resources.update(candidate_resources)
                batch_end += 1
        batch = prepared_calls[call_index:batch_end]

        # An ask/connection preflight is a barrier for the untouched batch
        # and every later batch. Persist only that exact waiting identity;
        # no sibling handler has started and no later Tool Call is crossed.
        waiting = next(
            (
                prepared_call
                for prepared_call in batch
                if prepared_call.execution_plan.requires_interaction
            ),
            None,
        )
        if waiting is not None:
            untouched = prepared_calls[call_index:]
            reserved_ids = {item.call.id for item in untouched}
            reserved = await defer_tool_calls(
                turn_id=ctx.turn_id,
                session_id=ctx.session_id,
                user_id=tool_catalog.user_pk if tool_catalog else 0,
                dispatch_generation=ctx.dispatch_generation,
                blocked_by_call_id=waiting.call.id,
                calls=[
                    {
                        "call_id": item.call.id,
                        "tool_name": item.call.name,
                        "arguments": item.dispatch_plan.arguments,
                        "effect": item.dispatch_plan.effect.value,
                        "timeout_seconds": settings.AGENT_TOOL_TIMEOUT_SECONDS,
                        "model_step": budget.steps,
                        "model_call_index": item.model_index,
                        "model_call_order": (
                            (ctx.dispatch_generation - 1) * 1_000_000
                            + budget.steps * 10_000
                            + item.model_index
                        ),
                        "handler_identity": (item.dispatch_plan.handler_identity),
                        "provider_identity": (item.dispatch_plan.provider_identity),
                        "connection_identity": (item.dispatch_plan.connection_identity),
                    }
                    for item in untouched
                ],
            )
            if reserved or not ctx.turn_id:
                ctx.extras["batch_reserved_tool_call_ids"] = reserved_ids
        active_batch = [waiting] if waiting is not None else batch
        starts: dict[int, float] = {}
        for prepared_call in active_batch:
            tc = prepared_call.call
            parsed_args = prepared_call.dispatch_plan.arguments
            tool_started = time.perf_counter()
            starts[prepared_call.model_index] = tool_started
            yield HarnessEvent.tool_start(
                tc.name,
                _args_summary(tc.arguments),
                step=budget.steps,
                elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                tool_call_id=tc.id,
                input=redact_tool_value(parsed_args),
            )

        async def run_indexed(
            prepared_call: _PreparedToolCall,
        ) -> tuple[int, dict[str, Any], str, float]:
            observation, result_text, latency_ms = await _run_tool(
                prepared_call,
                starts[prepared_call.model_index],
                ctx=ctx,
                dispatcher=dispatcher,
                user_pk=tool_catalog.user_pk if tool_catalog else 0,
            )
            return (
                prepared_call.model_index,
                observation,
                result_text,
                latency_ms,
            )

        tasks = [asyncio.create_task(run_indexed(item)) for item in active_batch]
        outcomes: dict[int, tuple[dict[str, Any], str, float]] = {}
        try:
            for completed in asyncio.as_completed(tasks):
                model_index, observation, result_text, latency_ms = await completed
                outcomes[model_index] = (observation, result_text, latency_ms)
                completed_call = prepared_calls[model_index].call
                tool_error = "error" in observation
                # Live completion order is the real network/handler order;
                # call identity lets the client update the original row.
                yield HarnessEvent.tool_done(
                    completed_call.name,
                    _result_summary(observation),
                    step=budget.steps,
                    elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                    tool_latency_ms=latency_ms,
                    is_error=tool_error,
                    result_content=result_text,
                    tool_call_id=completed_call.id,
                )
                if observation.get("error") in {
                    "interaction_required",
                    "connection_required",
                    "policy_required",
                }:
                    ctx.extras["interaction_required"] = {
                        "tool_call_id": completed_call.id,
                        "kind": observation.get("interaction_type", "approval"),
                    }
                    interaction = observation.get("interaction")
                    if isinstance(interaction, dict):
                        yield HarnessEvent.interaction(
                            interaction,
                            step=budget.steps,
                            elapsed_ms=round(budget.elapsed_seconds * 1000, 2),
                        )
        finally:
            pending = [task for task in tasks if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        # The model and durable Conversation projection remain in original
        # model-call index order, independent of live completion order.
        for prepared_call in active_batch:
            tc = prepared_call.call
            parsed_args = prepared_call.dispatch_plan.arguments
            observation, result_text, latency_ms = outcomes[prepared_call.model_index]
            tool_name = tc.name
            tool_error = "error" in observation
            # Canonical typed arguments make whitespace/key-order variants
            # the same action for repeat and failure-loop detection.
            canonical_args = json.dumps(
                parsed_args,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            signature = f"{tool_name}\x00{canonical_args}"
            repeat_count = budget.consume_tool_call(tool_name, signature)
            await persist_turn_budget(ctx.turn_id, budget.to_dict())
            if repeat_count in (_REPEAT_NUDGE_SOFT, _REPEAT_NUDGE_FIRM):
                nudge_repeat, nudge_tool = repeat_count, tool_name

            logger.info(
                "tool_metric | tool=%s latency_ms=%.1f is_error=%s result_chars=%d step=%d",
                tool_name,
                latency_ms,
                tool_error,
                len(safe_json_dumps(observation)),
                budget.steps,
            )

            incident = budget.observe_tool_result(
                tool_name,
                signature,
                result_text,
                is_error=tool_error,
            )
            if incident:
                replan_message = incident
            from app.conversation.context_reduction import tool_message

            tool_msg = tool_message(tc.id, result_text, ctx.turn_id)
            messages.append(tool_msg)

            # Persistent chain (frontend folded-card replay).
            # Keep the redacted result for replay; model-only projection
            # happens later in the shared context reducer. The frontend
            # renders content in the expanded view and summary in its label.
            blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": redact_tool_value(parsed_args),
                }
            )
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "source_turn_id": ctx.turn_id,
                    "is_error": tool_error,
                    "latency_ms": latency_ms,
                    "summary": _result_summary(observation),
                    "content": result_text,
                }
            )

        call_index = batch_end
        if waiting is not None or ctx.extras.get("interaction_required"):
            break

    # Repeated identical tool calls: steer the model with a soft nudge
    # appended AFTER the tool results (never a hard stop). Placed after the
    # results so the
    # assistant(tool_calls)→tool→tool pairing stays intact.
    if nudge_repeat:
        messages.append(
            runtime_control_message(
                "repeat_call_recovery",
                _repeat_call_nudge(nudge_tool, nudge_repeat),
            )
        )
    if replan_message:
        messages.append(
            runtime_control_message(
                "tool_failure_replan",
                replan_message + " Revise the approach before continuing.",
            )
        )
