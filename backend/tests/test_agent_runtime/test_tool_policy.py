import pytest
from app.agent_runtime.tool_policy import (
    ToolEffect,
    ToolPolicyContext,
    evaluate_tool_policy,
)


@pytest.mark.parametrize(
    ("context", "outcome", "reason"),
    [
        (ToolPolicyContext(), "allow", "read_allowed"),
        (
            ToolPolicyContext(connection_ready=False),
            "ask",
            "connection_required",
        ),
        (
            ToolPolicyContext(provider_scope_allows=False),
            "deny",
            "provider_scope_denied",
        ),
        (
            ToolPolicyContext(hard_deny_reason="product_boundary"),
            "deny",
            "product_boundary",
        ),
    ],
)
def test_read_policy_follows_hard_boundary_connection_scope_order(
    context, outcome, reason
):
    decision = evaluate_tool_policy(ToolEffect.READ, context)
    assert (decision.outcome, decision.reason) == (outcome, reason)


def test_standard_external_write_asks_unless_same_call_was_confirmed():
    pending = evaluate_tool_policy(
        ToolEffect.EXTERNAL_WRITE,
        ToolPolicyContext(current_task_authorizes=True),
    )
    confirmed = evaluate_tool_policy(
        ToolEffect.EXTERNAL_WRITE,
        ToolPolicyContext(
            current_task_authorizes=True,
            user_confirmed_this_call=True,
        ),
    )
    assert pending.outcome == "ask"
    assert confirmed.outcome == "allow"


def test_internal_write_can_resume_after_this_exact_call_is_confirmed():
    pending = evaluate_tool_policy(
        ToolEffect.INTERNAL_WRITE,
        ToolPolicyContext(),
    )
    decision = evaluate_tool_policy(
        ToolEffect.INTERNAL_WRITE,
        ToolPolicyContext(user_confirmed_this_call=True),
    )
    assert pending.outcome == "ask"
    assert pending.reason == "internal_write_not_explicit"
    assert decision.outcome == "allow"
    assert decision.reason == "call_confirmed_internal_write"


def test_client_action_can_resume_only_after_this_call_is_confirmed():
    pending = evaluate_tool_policy(ToolEffect.CLIENT_ACTION, ToolPolicyContext())
    confirmed = evaluate_tool_policy(
        ToolEffect.CLIENT_ACTION,
        ToolPolicyContext(user_confirmed_this_call=True),
    )
    assert (pending.outcome, pending.reason) == (
        "ask",
        "client_action_confirmation_required",
    )
    assert (confirmed.outcome, confirmed.reason) == (
        "allow",
        "call_confirmed_client_action",
    )


def test_auto_only_skips_ordinary_external_confirmation_inside_task_scope():
    allowed = evaluate_tool_policy(
        ToolEffect.EXTERNAL_WRITE,
        ToolPolicyContext(
            execution_mode="auto",
            current_task_authorizes=True,
            reversible=True,
        ),
    )
    outside_scope = evaluate_tool_policy(
        ToolEffect.EXTERNAL_WRITE,
        ToolPolicyContext(execution_mode="auto"),
    )
    retained = evaluate_tool_policy(
        ToolEffect.EXTERNAL_WRITE,
        ToolPolicyContext(
            execution_mode="auto",
            current_task_authorizes=True,
            reversible=True,
            user_retained_decision=True,
        ),
    )
    irreversible = evaluate_tool_policy(
        ToolEffect.EXTERNAL_WRITE,
        ToolPolicyContext(
            execution_mode="auto",
            current_task_authorizes=True,
            reversible=False,
        ),
    )
    assert allowed.outcome == "allow"
    assert allowed.reason == "auto_scope_authorized_reversible"
    assert outside_scope.outcome == "ask"
    assert retained.outcome == "ask"
    assert irreversible.outcome == "ask"


def test_unknown_effect_fails_closed():
    assert (
        evaluate_tool_policy(ToolEffect.UNKNOWN, ToolPolicyContext()).outcome == "ask"
    )


def test_unknown_effect_resumes_only_after_exact_call_confirmation():
    decision = evaluate_tool_policy(
        ToolEffect.UNKNOWN,
        ToolPolicyContext(user_confirmed_this_call=True),
    )
    assert (decision.outcome, decision.reason) == (
        "allow",
        "call_confirmed_unknown_effect",
    )


def test_runtime_control_does_not_require_product_write_approval():
    decision = evaluate_tool_policy(ToolEffect.RUNTIME_CONTROL, ToolPolicyContext())
    assert (decision.outcome, decision.reason) == (
        "allow",
        "runtime_control_allowed",
    )
