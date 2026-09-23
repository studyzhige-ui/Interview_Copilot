"""Release regressions converted from the original audit failure cases."""

import asyncio
from types import SimpleNamespace
import pytest


@pytest.mark.asyncio
async def test_event_transport_failure_does_not_fail_execution(monkeypatch):
    from app.services.chat import turn_executor
    from redis.exceptions import ConnectionError

    async def unavailable(*args):
        raise ConnectionError("Redis restarted")

    monkeypatch.setattr(turn_executor.turn_event_buffer, "append", unavailable)
    await turn_executor._publish_event("turn", '{"type":"text"}')


@pytest.mark.asyncio
async def test_shutdown_closes_all_resources_even_when_one_close_fails():
    from app.core.runtime_resources import current_resources, close_current_resources

    closed = []

    class Client:
        def __init__(self, name, fails=False):
            self.name, self.fails = name, fails

        async def aclose(self):
            closed.append(self.name)
            if self.fails:
                raise OSError("close failed")

    resources = current_resources()
    resources.redis.update(first=Client("first", True), second=Client("second"))
    await close_current_resources()
    assert set(closed) == {"first", "second"}
    assert current_resources() is not resources
    await close_current_resources()


def test_running_cancel_survives_transport_loss(db_session, monkeypatch):
    from app.models.user import User
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.services.chat import turn_executor

    user = User(username="cancel-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(
        id="cancel-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="cancel-turn",
    )
    turn = ConversationTurn(
        id="cancel-turn",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="work",
        status="running",
    )
    db_session.add_all([conversation, turn])
    db_session.commit()
    assert not turn_executor.cancel_pending_turn(db_session, turn.id, user.id)
    db_session.expire_all()
    assert db_session.get(ConversationTurn, turn.id).cancel_requested is True
    assert db_session.get(ConversationTurn, turn.id).status == "running"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_down", [False, True])
async def test_turn_commits_before_done_and_survives_event_loss(
    monkeypatch, transport_down
):
    import app.conversation as conversation
    from app.conversation.events import HarnessEvent
    from app.services.chat import turn_executor as executor
    from redis.exceptions import ConnectionError

    order = []
    attempts = []
    turn = executor.TurnExecution(
        id="durable",
        mode="chat",
        conversation_id="session",
        message="hello",
        username="user",
    )
    monkeypatch.setattr(executor, "_claim", lambda _: turn)
    monkeypatch.setattr(executor, "_cancellation_requested", lambda _: False)
    monkeypatch.setattr(executor, "_has_assistant", lambda _: True)
    monkeypatch.setattr(executor, "_finish", lambda *args: order.append("committed"))

    class Engine:
        outcome = "completed"

        def __init__(self, **kwargs):
            pass

        async def submit_message(self):
            yield HarnessEvent.text("answer", step=0, elapsed_ms=0)
            yield HarnessEvent.text("answer continued", step=0, elapsed_ms=0)
            yield HarnessEvent.done(step=0, elapsed_ms=0)

    async def append(_, event):
        import json

        attempts.append(event)
        if transport_down:
            raise ConnectionError("offline")
        order.append(json.loads(event)["type"])
        return "1-0"

    monkeypatch.setattr(conversation, "ConversationEngine", Engine)
    monkeypatch.setattr(executor.turn_event_buffer, "append", append)
    await executor.execute_turn(turn.id)
    assert "committed" in order
    if transport_down:
        assert len(attempts) == 1
    else:
        assert order[-2:] == ["committed", "done"]


@pytest.mark.asyncio
async def test_lost_cancellation_control_stops_the_paid_execution(monkeypatch):
    import app.conversation as conversation
    from app.services.chat import turn_executor as executor

    started = asyncio.Event()
    stopped = []
    settled = []
    turn = executor.TurnExecution(
        id="control-loss",
        mode="chat",
        conversation_id="session",
        message="hello",
        username="user",
    )
    monkeypatch.setattr(executor, "_claim", lambda _: turn)

    def unavailable(_):
        raise ConnectionError("database unavailable")

    async def read_control(fn, *args, **kwargs):
        if fn is unavailable:
            await started.wait()
        return fn(*args, **kwargs)

    monkeypatch.setattr(executor, "_cancellation_requested", unavailable)
    monkeypatch.setattr(executor.asyncio, "to_thread", read_control)
    monkeypatch.setattr(executor, "_finish", lambda *args: settled.append(args))

    class Engine:
        outcome = "completed"

        def __init__(self, **kwargs):
            pass

        async def submit_message(self):
            started.set()
            try:
                await asyncio.Event().wait()
                yield
            finally:
                stopped.append(True)

        async def persist_background_failure(self, failure):
            assert "控制连接" in failure

    async def append(*args):
        return "1-0"

    monkeypatch.setattr(conversation, "ConversationEngine", Engine)
    monkeypatch.setattr(executor.turn_event_buffer, "append", append)
    await asyncio.wait_for(executor.execute_turn(turn.id), timeout=2)
    assert stopped == [True]
    assert settled[0][1] == "failed"


@pytest.mark.asyncio
async def test_agent_usage_limit_stops_before_another_paid_call(monkeypatch):
    from app.agent_runtime.react_agent import AgentRunState
    from app.conversation.agent_strategy import AgentLoopStrategy
    from app.conversation.strategy import StrategyContext
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_RUN_MAX_TOTAL_TOKENS", 100)
    budget = AgentRunState(started_at=0, prompt_tokens=100)
    ctx = StrategyContext(user_id="user", session_id="session", user_message="continue")
    events = [
        event
        async for event in AgentLoopStrategy()._loop(
            ctx=ctx,
            messages=[],
            blocks=[],
            budget=budget,
            client=None,
            profile=None,
            compactor=None,
            tool_catalog=None,
            tool_schemas=[],
            base_task_content="continue",
        )
    ]
    assert events and budget.stop_reason == "resource_token_limit"
    assert budget.steps == 0
    assert ctx.extras["_terminal_outcome"] == "blocked"


@pytest.mark.asyncio
async def test_sse_redis_failure_recovers_durable_terminal(monkeypatch):
    from app.api.chat import streaming
    from app.services.chat.turn_event_buffer import turn_event_buffer

    monkeypatch.setattr(streaming, "resolve_user_pk", lambda *args: 1)
    db = SimpleNamespace(
        get=lambda *args: SimpleNamespace(conversation_id="conv", user_id=1)
    )
    calls = []
    monkeypatch.setattr(
        streaming,
        "_turn_terminal_state",
        lambda *args: calls.append("db") or ("completed", None),
    )

    async def broken_read(*args):
        raise ConnectionError("isolated redis outage")

    monkeypatch.setattr(turn_event_buffer, "read", broken_read)
    response = streaming.stream_chat_turn_events(
        "conv",
        "turn",
        after=None,
        last_event_id=None,
        current_user=SimpleNamespace(username="audit"),
        db=db,
    )
    events = [event async for event in response.body_iterator]
    assert calls == ["db"]
    assert any("done" in event for event in events)


def test_native_clients_are_owned_by_distinct_loops(monkeypatch):
    from app.core import llm_client_factory as factory

    monkeypatch.setattr(factory, "resolve_api_key", lambda *a, **k: "fake-key")
    monkeypatch.setattr(
        factory, "_load_user_provider_overrides", lambda *a: factory._NO_OVERRIDES
    )
    monkeypatch.setattr(factory, "AsyncOpenAI", lambda **kwargs: object())
    profile = SimpleNamespace(id="audit-profile", api_base="https://example.invalid")

    async def acquire():
        return asyncio.get_running_loop(), await factory.get_async_openai_client(
            profile, "audit-user"
        )

    loop1, loop2 = asyncio.new_event_loop(), asyncio.new_event_loop()
    try:
        first = loop1.run_until_complete(acquire())
        second = loop2.run_until_complete(acquire())
        assert first[0] is not second[0]
        assert first[1] is not second[1]
    finally:
        loop1.close()
        loop2.close()


@pytest.mark.asyncio
async def test_queue_wait_does_not_expire_running_lease(monkeypatch):
    from datetime import timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.database import Base
    from app.db.types import utc_now
    from app.models.user import User
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.services.chat import turn_executor as executor

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username="audit-only", hashed_password="x")
        db.add(user)
        db.flush()
        conv = Conversation(
            id="audit-conv",
            user_id=user.id,
            title="audit",
            type="general",
            active_turn_id="audit-turn",
        )
        turn = ConversationTurn(
            id="audit-turn",
            conversation_id=conv.id,
            user_id=user.id,
            mode="agent",
            message="queued",
            status="pending",
            created_at=utc_now() - timedelta(seconds=61),
        )
        db.add_all([conv, turn])
        db.commit()
    monkeypatch.setattr(executor, "SessionLocal", sessions)
    monkeypatch.setattr(executor.settings, "TURN_STALE_SECONDS", 60)
    monkeypatch.setattr(
        executor, "_admit_persistent_task_after_user_terminal", lambda *a, **k: None
    )
    monkeypatch.setattr(
        executor.transcript_service, "complete_background_turn", lambda **k: 2
    )

    async def append(*args):
        return "1-0"

    monkeypatch.setattr(executor.turn_event_buffer, "append", append)
    try:
        assert await executor.fail_orphaned_turns() == 0
        with sessions() as db:
            turn = db.get(ConversationTurn, "audit-turn")
            assert turn.status == "pending" and turn.started_at is None
    finally:
        engine.dispose()


def test_expired_outbox_owner_cannot_overwrite_new_owner_success(monkeypatch):
    from datetime import timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.database import Base
    from app.db.types import utc_now
    from app.models.outbox_job import OutboxJob
    from app.services import outbox

    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    initial = utc_now()
    clock = [initial]
    monkeypatch.setattr(outbox, "utc_now", lambda: clock[0])
    attempts = []

    def handler(db, job):
        attempts.append(job.locked_by)
        if len(attempts) == 1:
            clock[0] = initial + timedelta(minutes=21)
            with sessions() as newer:
                assert outbox.run_due_outbox_jobs(newer, limit=1) == 1
                assert newer.get(OutboxJob, "audit-job").status == "succeeded"
            raise TimeoutError("old worker returns after lease was reassigned")

    monkeypatch.setattr(outbox, "_HANDLERS", {"audit_probe": handler})
    try:
        with sessions() as db:
            db.add(
                OutboxJob(
                    id="audit-job",
                    user_id=1,
                    job_type="audit_probe",
                    status="pending",
                    attempts=0,
                    max_attempts=5,
                    next_run_at=initial,
                )
            )
            db.commit()
            assert outbox.run_due_outbox_jobs(db, limit=1) == 1
        with sessions() as db:
            assert len(attempts) == 2
            assert db.get(OutboxJob, "audit-job").status == "succeeded"
    finally:
        engine.dispose()
