from app.models.chat import Conversation
from app.models.user import User
from app.services.capabilities import conversation_capability_service


def _state(db_session):
    user = User(username="capability-state", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, title="state")
    db_session.add(conversation)
    db_session.commit()
    return (
        user,
        conversation,
        conversation_capability_service.get_or_create(
            db_session,
            conversation.id,
            user.id,
        ),
    )


def test_session_permissions_discovery_and_bounded_history(db_session):
    _user, _conversation, state = _state(db_session)
    conversation_capability_service.set_permission(
        db_session,
        state,
        "mcp_server:7",
        "deny",
    )
    assert (
        conversation_capability_service.permission_for(
            state,
            "mcp__demo__add",
            server_id=7,
        )
        == "deny"
    )

    conversation_capability_service.record_discovered_skills(
        db_session,
        state,
        ["plan", "plan", "review"],
    )
    for index in range(55):
        conversation_capability_service.append_tool_history(
            db_session,
            state,
            tool_name=f"tool-{index}",
            status="completed",
            turn_id="turn",
        )
    payload = conversation_capability_service.payload(state)
    assert payload["discovered_skills"] == ["plan", "review"]
    assert len(payload["tool_history"]) == 50
    assert payload["tool_history"][0]["tool_name"] == "tool-5"


def test_session_state_enforces_owner(db_session):
    _user, conversation, _state_row = _state(db_session)
    other = User(username="other-capability-state", hashed_password="x")
    db_session.add(other)
    db_session.commit()
    try:
        conversation_capability_service.get_or_create(
            db_session, conversation.id, other.id
        )
    except ValueError as exc:
        assert str(exc) == "Conversation not found"
    else:
        raise AssertionError("cross-user capability state was exposed")
