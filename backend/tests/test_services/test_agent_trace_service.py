"""Tests for app.services.agent_trace_service.

The shared conftest db_session fixture imports a stale ``app.models.interview``
module that was removed during the refactor, so we build our own in-process
SQLite session here. The service only touches the AgentRun/AgentStep tables.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def trace_db_session():
    """Isolated SQLite engine containing only the agent_trace tables."""
    import app.models.agent_trace  # noqa: F401 — register tables on Base
    from app.db.database import Base

    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[
        Base.metadata.tables["agent_runs"],
        Base.metadata.tables["agent_steps"],
    ])
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_agent_trace_service_full_lifecycle(monkeypatch, trace_db_session):
    """create_run → append_step → finish_run → read back → metrics."""
    from app.services import agent_trace_service as svc

    # Service uses module-level SessionLocal; redirect to our test session.
    monkeypatch.setattr(svc, "SessionLocal", lambda: _NoCloseSession(trace_db_session))

    run_id = asyncio.run(svc.create_run(user_id="alice", session_id="s1", goal="find jobs"))
    assert run_id

    asyncio.run(
        svc.append_step(
            run_id=run_id,
            step_index=1,
            action_type="tool_call",
            tool_name="search_jobs",
            tool_call_id="call_1",
            tool_args={"keywords": "python"},
            observation={"count": 2},
            assistant_content="",
            is_error=False,
            latency_ms=12.3,
        )
    )

    asyncio.run(
        svc.finish_run(
            run_id=run_id,
            status="completed",
            final_answer="done",
            steps_used=2,
            tool_calls=1,
            prompt_tokens=100,
            completion_tokens=20,
            total_latency_ms=234.5,
        )
    )

    run_payload = asyncio.run(svc.get_run_with_steps(run_id=run_id, user_id="alice"))
    assert run_payload is not None
    assert run_payload["status"] == "completed"
    assert run_payload["final_answer"] == "done"
    assert run_payload["steps"][0]["tool_name"] == "search_jobs"
    assert run_payload["steps"][0]["tool_args"] == {"keywords": "python"}

    run_list = asyncio.run(svc.list_runs(user_id="alice", session_id="s1", limit=10, offset=0))
    assert len(run_list) == 1

    metrics = asyncio.run(svc.aggregate_trajectory_metrics(user_id="alice", session_id="s1"))
    assert metrics["run_count"] == 1
    assert metrics["completion_rate"] == 1.0
    assert metrics["avg_tool_calls"] == 1.0


def test_agent_trace_service_user_scope(monkeypatch, trace_db_session):
    """get_run_with_steps must filter by user_id (no cross-user leakage)."""
    from app.services import agent_trace_service as svc

    monkeypatch.setattr(svc, "SessionLocal", lambda: _NoCloseSession(trace_db_session))

    run_id = asyncio.run(svc.create_run(user_id="alice", session_id="s", goal="g"))

    # Wrong user → None
    leak = asyncio.run(svc.get_run_with_steps(run_id=run_id, user_id="bob"))
    assert leak is None


def test_aggregate_metrics_empty(monkeypatch, trace_db_session):
    """No runs for the user → all-zero metrics, no division by zero."""
    from app.services import agent_trace_service as svc

    monkeypatch.setattr(svc, "SessionLocal", lambda: _NoCloseSession(trace_db_session))

    metrics = asyncio.run(svc.aggregate_trajectory_metrics(user_id="ghost", session_id=None))
    assert metrics["run_count"] == 0
    assert metrics["completion_rate"] == 0.0
    assert metrics["avg_steps"] == 0.0


class _NoCloseSession:
    """Wrap a real SQLAlchemy session so .close() is a no-op.

    The service treats every call to SessionLocal() as a fresh session and
    closes it in its finally block; in tests we want a single long-lived
    session so we can assert state across calls.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        # Flush so subsequent SessionLocal() reads see the writes.
        try:
            self._inner.commit()
        except Exception:
            self._inner.rollback()
