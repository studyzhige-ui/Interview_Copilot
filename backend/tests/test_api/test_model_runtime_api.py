from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client():
    from app.api import model_runtime
    from app.core.security import get_current_user

    class FakeUser:
        username = "alice"

    async def fake_user():
        return FakeUser()

    app = FastAPI()
    app.include_router(model_runtime.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app), model_runtime


def test_model_catalog_endpoint(monkeypatch):
    client, model_api = _build_client()

    monkeypatch.setattr(model_api, "get_runtime_selection", lambda: {"primary": "deepseek-reasoner", "fast": "deepseek-chat", "agent": "deepseek-chat"})
    monkeypatch.setattr(model_api, "list_profiles", lambda: [{"id": "deepseek-chat", "ready": True}])

    resp = client.get("/api/v1/models/catalog", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["selection"]["agent"] == "deepseek-chat"
    assert payload["profiles"][0]["id"] == "deepseek-chat"


def test_update_model_runtime_endpoint(monkeypatch):
    client, model_api = _build_client()

    refreshed = {"called": False}

    monkeypatch.setattr(model_api, "validate_role_update", lambda role, profile_id: None)
    monkeypatch.setattr(
        model_api,
        "update_runtime_selection",
        lambda updates: {"primary": "deepseek-reasoner", "fast": updates["fast"], "agent": "deepseek-chat"},
    )
    monkeypatch.setattr(model_api, "refresh_primary_llm", lambda: refreshed.__setitem__("called", True))

    resp = client.put(
        "/api/v1/models/runtime",
        json={"fast": "nvidia-meta-llama-3.1-8b"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["selection"]["fast"] == "nvidia-meta-llama-3.1-8b"
    assert refreshed["called"] is True
