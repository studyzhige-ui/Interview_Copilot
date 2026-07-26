from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
from app.models.conversation_turn import ConversationTurn
from app.models.user import User
from app.services.chat import agent_recovery_service
from app.services.chat.session_task_service import create_task


SESSION_ID = "recovery-session"


def test_checkpoint_and_tool_audit_are_recoverable(db_session):
    user = User(username="recovery-user", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(Conversation(id=SESSION_ID, user_id=user.id, title="recovery"))
    db_session.flush()
    task = create_task(db_session, SESSION_ID, "Gather evidence")
    turn = ConversationTurn(
        id="recovery-turn",
        conversation_id=SESSION_ID,
        user_id=user.id,
        mode="agent",
        message="work",
    )
    db_session.add(turn)
    db_session.flush()
    db_session.add(
        AgentToolCall(
            call_id="call-1",
            turn_id=turn.id,
            session_id=SESSION_ID,
            user_id=user.id,
            tool_name="task_get",
            arguments_json={"task_id": task["task_id"]},
            timeout_seconds=30,
            status="completed",
            result_json={"status": "pending"},
        )
    )
    db_session.commit()
    agent_recovery_service.save_checkpoint(
        db_session,
        SESSION_ID,
        summary="Task created and ready",
        current_task_id=task["task_id"],
        next_action="Run the evidence retrieval tool",
    )

    state = agent_recovery_service.load_recovery_state(db_session, SESSION_ID)
    assert state["checkpoint"]["next_action"] == "Run the evidence retrieval tool"
    assert state["recent_events"] == [
        {
            "tool": "task_get",
            "payload": {
                "arguments": {"task_id": task["task_id"]},
                "result": {"status": "pending"},
                "status": "completed",
                "error": None,
            },
            "created_at": state["recent_events"][0]["created_at"],
        }
    ]
    assert state["tasks"][0]["task_id"] == task["task_id"]
