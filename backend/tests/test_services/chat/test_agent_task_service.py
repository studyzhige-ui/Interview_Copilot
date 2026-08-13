from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.models.agent_task import AgentTask, AgentTaskRevision
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.schemas.agent_task import (
    AgentTaskView,
    CreateAgentTaskRequest,
    ReviseAgentTaskRequest,
)
from app.services.chat.agent_task_service import (
    AgentTaskConflictError,
    AgentTaskFrozenError,
    AgentTaskOwnershipError,
    agent_task_structure_complete,
    create_agent_task,
    freeze_agent_task_for_terminal_turn,
    get_agent_task,
    revise_agent_task,
)


def _seed_turn(db_session, *, status: str = "running", mode: str = "agent"):
    suffix = uuid.uuid4().hex
    user = User(username=f"agent-task-{suffix}", hashed_password="test-hash")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, mode=mode)
    db_session.add(conversation)
    db_session.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode=mode,
        message="complete this complex request",
        status=status,
    )
    db_session.add(turn)
    db_session.flush()
    return user, conversation, turn


def _create_request(*, key: str = "create-1") -> CreateAgentTaskRequest:
    return CreateAgentTaskRequest(
        objective="Compare the roles and deliver the saved recommendation",
        completion_conditions=[
            "Both roles have been compared",
            "The requested artifact has been saved",
        ],
        phases=[
            {
                "id": "compare",
                "title": "Compare the two roles",
                "status": "in_progress",
            },
            {
                "id": "deliver",
                "title": "Save and deliver the recommendation",
                "status": "pending",
            },
        ],
        idempotency_key=key,
    )


def _revision(
    *,
    expected_version: int,
    key: str,
    first_status: str = "completed",
    second_status: str = "in_progress",
) -> ReviseAgentTaskRequest:
    return ReviseAgentTaskRequest(
        objective="Compare the roles and deliver the saved recommendation",
        completion_conditions=[
            "Both roles have been compared",
            "The requested artifact has been saved",
        ],
        phases=[
            {
                "id": "compare",
                "title": "Compare the two roles",
                "status": first_status,
                "result_refs": [{"owner": "tool_call", "identity": "provider-call-42"}],
            },
            {
                "id": "deliver",
                "title": "Save and deliver the recommendation",
                "status": second_status,
            },
        ],
        expected_version=expected_version,
        idempotency_key=key,
        reason="The comparison is complete, so delivery is now active",
    )


def test_plan_schema_is_flat_bounded_and_identity_only():
    with pytest.raises(ValidationError, match="at most one phase"):
        CreateAgentTaskRequest(
            objective="Complex request",
            completion_conditions=["Done"],
            phases=[
                {"id": "one", "title": "One", "status": "in_progress"},
                {"id": "two", "title": "Two", "status": "in_progress"},
            ],
            idempotency_key="key",
        )

    with pytest.raises(ValidationError, match="extra_forbidden"):
        CreateAgentTaskRequest(
            objective="Complex request",
            completion_conditions=["Done"],
            phases=[
                {
                    "id": "one",
                    "title": "One",
                    "status": "in_progress",
                    "result_refs": [
                        {
                            "owner": "artifact",
                            "identity": "artifact-1",
                            "content": "must not be copied",
                        }
                    ],
                },
                {"id": "two", "title": "Two", "status": "pending"},
            ],
            idempotency_key="key",
        )


def test_create_is_explicit_owner_checked_idempotent_and_one_per_turn(db_session):
    user, _conversation, turn = _seed_turn(db_session)
    request = _create_request()

    task = create_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=request,
    )
    replay = create_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=request,
    )

    assert replay is task
    assert db_session.query(AgentTask).filter_by(turn_id=turn.id).count() == 1
    assert task.version == 1
    assert task.phases_json[0]["status"] == "in_progress"
    view = AgentTaskView.model_validate(task)
    assert view.phases[0].id == "compare"
    assert view.completion_conditions == request.completion_conditions

    with pytest.raises(AgentTaskConflictError, match="already has"):
        create_agent_task(
            db_session,
            turn_id=turn.id,
            user_id=user.id,
            request=_create_request(key="different-create"),
        )

    stranger = User(
        username=f"stranger-{uuid.uuid4().hex}", hashed_password="test-hash"
    )
    db_session.add(stranger)
    db_session.flush()
    with pytest.raises(AgentTaskOwnershipError):
        get_agent_task(db_session, turn_id=turn.id, user_id=stranger.id)


def test_create_rejects_simple_chat_and_terminal_turn(db_session):
    chat_user, _conversation, chat_turn = _seed_turn(db_session, mode="chat")
    with pytest.raises(AgentTaskConflictError, match="Agent Turn"):
        create_agent_task(
            db_session,
            turn_id=chat_turn.id,
            user_id=chat_user.id,
            request=_create_request(),
        )

    terminal_user, _conversation, terminal_turn = _seed_turn(
        db_session, status="completed"
    )
    with pytest.raises(AgentTaskFrozenError):
        create_agent_task(
            db_session,
            turn_id=terminal_turn.id,
            user_id=terminal_user.id,
            request=_create_request(),
        )


def test_revise_is_cas_idempotent_and_records_small_revision(db_session):
    user, _conversation, turn = _seed_turn(db_session)
    task = create_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=_create_request(),
    )
    request = _revision(expected_version=1, key="advance-1")

    revised = revise_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=request,
    )
    replay = revise_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=request,
    )

    assert revised.version == 2
    assert replay.version == 2
    assert revised.phases_json[0]["result_refs"] == [
        {"owner": "tool_call", "identity": "provider-call-42"}
    ]
    revisions = (
        db_session.query(AgentTaskRevision)
        .filter(AgentTaskRevision.agent_task_id == task.id)
        .all()
    )
    assert len(revisions) == 1
    assert revisions[0].from_version == 1
    assert revisions[0].to_version == 2
    assert revisions[0].changed_phase_ids_json == ["compare", "deliver"]
    assert not hasattr(revisions[0], "tool_log_json")

    with pytest.raises(AgentTaskConflictError, match="current version is 2"):
        revise_agent_task(
            db_session,
            turn_id=turn.id,
            user_id=user.id,
            request=_revision(expected_version=1, key="stale-update"),
        )


def test_completed_phase_cannot_be_rewritten_or_removed(db_session):
    user, _conversation, turn = _seed_turn(db_session)
    create_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=_create_request(),
    )
    revise_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=_revision(expected_version=1, key="advance-1"),
    )
    rewritten = _revision(expected_version=2, key="rewrite-completed")
    rewritten.phases[0].title = "Silently changed conclusion"

    with pytest.raises(AgentTaskConflictError, match="completed"):
        revise_agent_task(
            db_session,
            turn_id=turn.id,
            user_id=user.id,
            request=rewritten,
        )


def test_waiting_keeps_plan_active_and_terminal_turn_freezes_snapshot(db_session):
    user, _conversation, turn = _seed_turn(db_session)
    task = create_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=_create_request(),
    )
    turn.status = "waiting"
    db_session.flush()

    assert task.phases_json[0]["status"] == "in_progress"
    revised = revise_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=ReviseAgentTaskRequest(
            **_plan_without_transport(_create_request()),
            expected_version=1,
            idempotency_key="waiting-replan",
            reason="New information changes a pending phase",
        ),
    )
    assert revised.version == 2

    turn.status = "cancelled"
    db_session.flush()
    frozen = freeze_agent_task_for_terminal_turn(db_session, turn_id=turn.id)
    assert frozen is not None
    assert frozen.frozen_at is not None
    assert freeze_agent_task_for_terminal_turn(db_session, turn_id=turn.id) is frozen

    with pytest.raises(AgentTaskFrozenError):
        revise_agent_task(
            db_session,
            turn_id=turn.id,
            user_id=user.id,
            request=ReviseAgentTaskRequest(
                **_plan_without_transport(_create_request()),
                expected_version=2,
                idempotency_key="after-terminal",
                reason="Must not revive a frozen plan",
            ),
        )


def _plan_without_transport(request: CreateAgentTaskRequest) -> dict:
    return request.model_dump(exclude={"idempotency_key"})


def test_structure_gate_only_checks_an_existing_plan(db_session):
    assert agent_task_structure_complete(None) is True
    user, _conversation, turn = _seed_turn(db_session)
    task = create_agent_task(
        db_session,
        turn_id=turn.id,
        user_id=user.id,
        request=_create_request(),
    )
    assert agent_task_structure_complete(task) is False
    task.phases_json = [
        {"id": "compare", "title": "Compare", "status": "completed"},
        {"id": "deliver", "title": "Deliver", "status": "skipped"},
    ]
    assert agent_task_structure_complete(task) is True
