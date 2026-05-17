"""API tests for ``app.api.agent`` — react agent + run inspection.

All endpoints are auth-gated, so we override ``get_current_user``; nothing
touches the DB so no SQLite setup is needed.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import agent as agent_api
from app.core.security import get_current_user


@pytest.fixture
def client():
    class FakeUser:
        username = "alice"

    async def fake_user():
        return FakeUser()

    app = FastAPI()
    app.include_router(agent_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app)


# ── /agent/react/chat ─────────────────────────────────────────────────────


def test_react_chat_returns_run_payload(client, monkeypatch):
    async def fake_run(user_message, user_id, session_id):
        assert user_id == "alice"
        assert session_id == "s1"
        return {
            "run_id": "run_1",
            "reply": "ok",
            "steps_used": 2,
            "tool_calls": 1,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "budget_stop_reason": None,
            "trace": [{"step": 1}],
        }

    from app.api.agent import react_agent as react_agent_mod
    monkeypatch.setattr(react_agent_mod, "run_react_agent", fake_run)

    resp = client.post(
        "/api/v1/agent/react/chat",
        json={"message": "help me", "include_trace": True},
        headers={"x-session-id": "s1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run_1"
    assert body["reply"] == "ok"
    assert body["trace"][0]["step"] == 1


def test_react_chat_omits_trace_unless_requested(client, monkeypatch):
    async def fake_run(user_message, user_id, session_id):
        return {
            "run_id": "run_2",
            "reply": "hi",
            "steps_used": 1,
            "tool_calls": 0,
            "prompt_tokens": 3,
            "completion_tokens": 1,
            "budget_stop_reason": None,
            "trace": [{"step": 1}],
        }

    from app.api.agent import react_agent as react_agent_mod
    monkeypatch.setattr(react_agent_mod, "run_react_agent", fake_run)

    resp = client.post("/api/v1/agent/react/chat", json={"message": "hi"})
    assert resp.status_code == 200
    body = resp.json()
    assert "trace" not in body


def test_react_chat_returns_500_on_runtime_error(client, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("agent kaput")

    from app.api.agent import react_agent as react_agent_mod
    monkeypatch.setattr(react_agent_mod, "run_react_agent", boom)

    resp = client.post("/api/v1/agent/react/chat", json={"message": "hi"})
    assert resp.status_code == 500
    assert "agent kaput" in resp.json()["detail"]


# ── /agent/runs ───────────────────────────────────────────────────────────


def test_list_runs_endpoint(client, monkeypatch):
    async def fake_list_runs(user_id, session_id, limit, offset):
        assert user_id == "alice"
        return [{"run_id": "run_1", "status": "completed"}]

    from app.api.agent import runs as runs_mod
    monkeypatch.setattr(runs_mod, "list_runs", fake_list_runs)

    resp = client.get("/api/v1/agent/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["runs"][0]["run_id"] == "run_1"


def test_get_run_endpoint_returns_404_when_missing(client, monkeypatch):
    async def fake_get_run(run_id, user_id):
        return None

    from app.api.agent import runs as runs_mod
    monkeypatch.setattr(runs_mod, "get_run_with_steps", fake_get_run)

    resp = client.get("/api/v1/agent/runs/does_not_exist")
    assert resp.status_code == 404


def test_get_run_endpoint_returns_payload(client, monkeypatch):
    async def fake_get_run(run_id, user_id):
        return {"run_id": run_id, "steps": [{"step_index": 1}]}

    from app.api.agent import runs as runs_mod
    monkeypatch.setattr(runs_mod, "get_run_with_steps", fake_get_run)

    resp = client.get("/api/v1/agent/runs/run_1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["run_id"] == "run_1"
    assert body["run"]["steps"][0]["step_index"] == 1


def test_metrics_endpoint(client, monkeypatch):
    async def fake_metrics(user_id, session_id):
        return {"run_count": 5, "avg_steps": 2.4}

    from app.api.agent import runs as runs_mod
    monkeypatch.setattr(runs_mod, "aggregate_trajectory_metrics", fake_metrics)

    resp = client.get("/api/v1/agent/metrics", params={"session_id": "s1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["metrics"]["run_count"] == 5


# ── /agent/chat (legacy) ──────────────────────────────────────────────────


def test_legacy_agent_chat_concatenates_chunks(client, monkeypatch):
    async def fake_stream(message, user_id, session_id):
        for piece in ["hel", "lo ", "world"]:
            yield piece

    import app.qa_pipeline.agent_executor as agent_executor_mod
    monkeypatch.setattr(agent_executor_mod, "stream_chat_with_agent", fake_stream)

    resp = client.post(
        "/api/v1/agent/chat",
        json={"message": "say hi"},
        headers={"x-session-id": "s1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["reply"] == "hello world"
