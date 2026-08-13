"""Parameter-level execution policy for concrete Tool calls.

Policy is a cross-cutting guard at the single Tool execution boundary.  It
does not discover tools, choose handlers, or create a second registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class ToolEffect(StrEnum):
    READ = "read"
    RUNTIME_CONTROL = "runtime_control"
    INTERNAL_WRITE = "internal_write"
    CLIENT_ACTION = "client_action"
    EXTERNAL_WRITE = "external_write"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ToolPolicyContext:
    execution_mode: Literal["standard", "auto"] = "standard"
    connection_ready: bool = True
    provider_scope_allows: bool = True
    current_task_authorizes: bool = False
    user_confirmed_this_call: bool = False
    reversible: bool = False
    hard_deny_reason: str | None = None
    user_retained_decision: bool = False


@dataclass(frozen=True)
class ToolPolicyDecision:
    outcome: Literal["allow", "ask", "deny"]
    reason: str


def evaluate_tool_policy(
    effect: ToolEffect,
    context: ToolPolicyContext,
) -> ToolPolicyDecision:
    """Evaluate one already-formed concrete call in the frozen policy order."""

    if context.hard_deny_reason:
        return ToolPolicyDecision("deny", context.hard_deny_reason)
    if not context.connection_ready:
        return ToolPolicyDecision("ask", "connection_required")
    if not context.provider_scope_allows:
        return ToolPolicyDecision("deny", "provider_scope_denied")
    if context.user_retained_decision:
        return ToolPolicyDecision("ask", "user_retained_decision")
    if effect is ToolEffect.READ:
        return ToolPolicyDecision("allow", "read_allowed")
    if effect is ToolEffect.RUNTIME_CONTROL:
        # Runtime-control tools only maintain the current admitted Turn's
        # execution projection (for example its optional AgentTask plan).
        # They cannot mutate product state or cross the Turn boundary.
        return ToolPolicyDecision("allow", "runtime_control_allowed")
    if effect is ToolEffect.INTERNAL_WRITE:
        if context.user_confirmed_this_call:
            return ToolPolicyDecision("allow", "call_confirmed_internal_write")
        if context.current_task_authorizes:
            return ToolPolicyDecision("allow", "task_authorized_internal_write")
        return ToolPolicyDecision("ask", "internal_write_not_explicit")
    if effect is ToolEffect.CLIENT_ACTION:
        if context.user_confirmed_this_call:
            return ToolPolicyDecision("allow", "call_confirmed_client_action")
        if context.current_task_authorizes and context.reversible:
            return ToolPolicyDecision(
                "allow", "task_authorized_reversible_client_action"
            )
        return ToolPolicyDecision("ask", "client_action_confirmation_required")
    if effect is ToolEffect.EXTERNAL_WRITE:
        if context.user_confirmed_this_call:
            return ToolPolicyDecision("allow", "call_confirmed")
        if (
            context.execution_mode == "auto"
            and context.current_task_authorizes
            and context.reversible
        ):
            return ToolPolicyDecision("allow", "auto_scope_authorized_reversible")
        return ToolPolicyDecision("ask", "external_write_confirmation_required")
    return ToolPolicyDecision("ask", "unknown_effect")
