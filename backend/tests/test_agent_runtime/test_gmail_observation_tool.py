from __future__ import annotations

import json

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, registry
from app.agent_runtime.tools.gmail_observation import _task_authorizes_review
from app.agent_runtime.turn_tool_catalog import (
    cloud_sustainable_automation_tool_names,
    cloud_sustainable_read_tool_names,
)


def _task_payload(*, action_scope: list[str] | None = None) -> str:
    return json.dumps(
        {
            "kind": "persistent_task_automation",
            "allowed_tool_names": ["review_gmail_observation"],
            "action_scope": action_scope or [],
            "triggers": [
                {
                    "kind": "event",
                    "source_identity": "gob_observation",
                }
            ],
        }
    )


def test_review_tool_is_exact_internal_automation_exception():
    definition = registry.snapshot().entries["review_gmail_observation"]

    assert definition.effect is ToolEffect.INTERNAL_WRITE
    assert definition.reversible is True
    assert "review_gmail_observation" not in cloud_sustainable_read_tool_names()
    assert "review_gmail_observation" in cloud_sustainable_automation_tool_names()


def test_task_authorizer_binds_exact_observation_and_auto_apply_scope():
    ctx = AgentToolContext(
        user_id="alice",
        user_pk=1,
        session_id="conversation-1",
        turn_id="turn-1",
    )
    confirm = {
        "observation_id": "gob_observation",
        "disposition": "needs_confirmation",
    }
    auto = {**confirm, "disposition": "auto_apply"}

    assert _task_authorizes_review(confirm, ctx, _task_payload()) is True
    assert (
        _task_authorizes_review(
            {**confirm, "observation_id": "gob_other"}, ctx, _task_payload()
        )
        is False
    )
    assert _task_authorizes_review(auto, ctx, _task_payload()) is False
    assert (
        _task_authorizes_review(
            auto,
            ctx,
            _task_payload(action_scope=["career.process_event.auto_apply"]),
        )
        is True
    )
    assert _task_authorizes_review(confirm, ctx, "provider-authored text") is False
