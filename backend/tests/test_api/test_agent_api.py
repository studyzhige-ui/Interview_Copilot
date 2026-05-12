from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client(monkeypatch):
    from app.api import agent as agent_api
    from app.core.security import get_current_user

    class FakeUser:
        username = "alice"

    async def fake_user():
        return FakeUser()

    app = FastAPI()
    app.include_router(agent_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app), agent_api


def test_react_agent_chat_endpoint(monkeypatch):
    client, agent_api = _build_client(monkeypatch)

    async def fake_run(user_message: str, user_id: str, session_id: str):
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
        json={"message": "help", "include_trace": True},
        headers={"Authorization": "Bearer fake", "x-session-id": "s1"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["run_id"] == "run_1"
    assert payload["trace"][0]["step"] == 1


def test_agent_trace_query_endpoints(monkeypatch):
    client, agent_api = _build_client(monkeypatch)

    async def fake_list_runs(user_id: str, session_id: str | None, limit: int, offset: int):
        return [{"run_id": "run_1", "status": "completed"}]

    async def fake_get_run_with_steps(run_id: str, user_id: str):
        return {"run_id": run_id, "steps": [{"step_index": 1}]}

    async def fake_metrics(user_id: str, session_id: str | None):
        return {"run_count": 1, "avg_steps": 2.0}

    from app.api.agent import runs as runs_mod
    monkeypatch.setattr(runs_mod, "list_runs", fake_list_runs)
    monkeypatch.setattr(runs_mod, "get_run_with_steps", fake_get_run_with_steps)
    monkeypatch.setattr(runs_mod, "aggregate_trajectory_metrics", fake_metrics)

    runs_resp = client.get(
        "/api/v1/agent/runs",
        headers={"Authorization": "Bearer fake"},
    )
    assert runs_resp.status_code == 200
    assert runs_resp.json()["runs"][0]["run_id"] == "run_1"

    run_resp = client.get(
        "/api/v1/agent/runs/run_1",
        headers={"Authorization": "Bearer fake"},
    )
    assert run_resp.status_code == 200
    assert run_resp.json()["run"]["run_id"] == "run_1"

    metrics_resp = client.get(
        "/api/v1/agent/metrics",
        headers={"Authorization": "Bearer fake"},
    )
    assert metrics_resp.status_code == 200
    assert metrics_resp.json()["metrics"]["run_count"] == 1
