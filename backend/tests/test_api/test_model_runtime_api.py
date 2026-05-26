"""API tests for ``app.api.model_runtime``.

The endpoints lean heavily on registry helpers and a Redis-backed cache;
we patch those out so tests don't reach external services.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import model_runtime as model_runtime_mod
from app.core.security import get_current_user


@pytest.fixture
def client():
    class FakeUser:
        username = "alice"

    async def fake_user():
        return FakeUser()

    app = FastAPI()
    app.include_router(model_runtime_mod.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    return TestClient(app)


# ── /models/catalog ───────────────────────────────────────────────────────


def test_models_catalog_returns_selection_and_profiles(client, monkeypatch):
    """P6-L: catalog is sourced from the pipeline cache, not from
    a static MODEL_PROFILES dict. We stub the pipeline load + the
    sync profile cache used to serialise the response."""
    from app.core.model_registry import ModelProfile

    fake_profiles = {
        "openai/gpt-4o": ModelProfile(
            id="openai/gpt-4o", provider="openai", display_name="GPT-4o",
            model="gpt-4o", api_base="https://x",
            api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        ),
        "openai/gpt-4o-mini": ModelProfile(
            id="openai/gpt-4o-mini", provider="openai", display_name="GPT-4o Mini",
            model="gpt-4o-mini", api_base="https://x",
            api_key_env="OPENAI_API_KEY", supports_function_calling=True,
        ),
    }
    monkeypatch.setattr(model_runtime_mod, "_get_all_profiles", lambda: fake_profiles)
    monkeypatch.setattr(
        model_runtime_mod,
        "get_runtime_selection",
        lambda user_id=None: {
            "primary": "openai/gpt-4o", "fast": "openai/gpt-4o-mini",
            "agent": "openai/gpt-4o", "mock_interview": "openai/gpt-4o",
        },
    )
    # profile_ready imported from registry — stub to True so the
    # serialiser sets ready=True without needing env vars set.
    monkeypatch.setattr(
        "app.core.model_registry.profile_ready",
        lambda profile, user_id=None: True,
    )

    async def fake_load_catalog():
        return {}  # empty → endpoint falls through to the planted profile cache

    monkeypatch.setattr(model_runtime_mod, "load_catalog", fake_load_catalog)

    # cached() goes via Redis — patch it to call the loader directly.
    async def fake_cached(name, ttl, loader):
        return await loader()

    with patch("app.services.cache_service.cached", side_effect=fake_cached):
        resp = client.get("/api/v1/models/catalog")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["selection"]["primary"] == "openai/gpt-4o"
    assert {p["id"] for p in body["profiles"]} == {"openai/gpt-4o", "openai/gpt-4o-mini"}


# ── /models/runtime (GET) ─────────────────────────────────────────────────


def test_models_runtime_get_resolves_each_role(client, monkeypatch):
    monkeypatch.setattr(
        model_runtime_mod,
        "get_runtime_selection",
        lambda user_id=None: {"primary": "p1", "fast": "p1", "agent": "p2", "mock_interview": "p1"},
    )

    class FakeProfile:
        def __init__(self, pid):
            self.id = pid
            self.provider = "openai"
            self.model = f"model-{pid}"
            self.display_name = pid

    monkeypatch.setattr(
        model_runtime_mod,
        "get_profile_for_role",
        lambda role, user_id=None: FakeProfile(f"p_{role}"),
    )
    resp = client.get("/api/v1/models/runtime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert set(body["resolved"].keys()) == {"primary", "fast", "agent", "mock_interview"}
    assert body["resolved"]["primary"]["profile_id"] == "p_primary"


# ── /models/runtime (PUT) ─────────────────────────────────────────────────


def test_update_runtime_rejects_empty_payload(client):
    resp = client.put("/api/v1/models/runtime", json={})
    assert resp.status_code == 400


def test_update_runtime_validates_and_persists(client, monkeypatch):
    calls = {"validate": 0, "refresh": 0}

    def fake_validate(role, profile_id, user_id=None):
        calls["validate"] += 1

    def fake_update(updates, user_id):
        # P6-C: ``update_runtime_selection`` now takes (updates, user_id)
        # so per-user storage is enforced at the call boundary.
        assert user_id, "endpoint must pass current_user.username"
        return {
            "primary": "p1",
            "fast": "p1",
            "agent": updates.get("agent", "p2"),
            "mock_interview": "p1",
        }

    def fake_refresh():
        calls["refresh"] += 1

    async def fake_invalidate(*_names):
        return None

    monkeypatch.setattr(model_runtime_mod, "validate_role_update", fake_validate)
    monkeypatch.setattr(model_runtime_mod, "update_runtime_selection", fake_update)
    monkeypatch.setattr(model_runtime_mod, "refresh_primary_llm", fake_refresh)

    with patch("app.services.cache_service.invalidate", side_effect=fake_invalidate):
        resp = client.put("/api/v1/models/runtime", json={"agent": "p_new"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["selection"]["agent"] == "p_new"
    assert calls["validate"] == 1
    assert calls["refresh"] == 1


def test_update_runtime_translates_value_error_to_400(client, monkeypatch):
    def bad_validate(role, profile_id, user_id=None):
        raise ValueError("invalid profile id")

    monkeypatch.setattr(model_runtime_mod, "validate_role_update", bad_validate)

    resp = client.put("/api/v1/models/runtime", json={"agent": "garbage"})
    assert resp.status_code == 400
    assert "invalid profile id" in resp.json()["detail"]


# ── /models/api-keys ──────────────────────────────────────────────────────


def test_list_my_api_keys_delegates(client):
    with patch(
        "app.services.user_api_key_service.list_user_api_keys",
        return_value=[{"provider": "openai", "masked_key": "sk-***abcd"}],
    ):
        resp = client.get("/api/v1/models/api-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert body["keys"][0]["provider"] == "openai"


def test_upsert_api_key_invalidates_caches(client, monkeypatch):
    async def fake_invalidate(*_names):
        return None

    with patch(
        "app.services.user_api_key_service.set_user_api_key",
        return_value={"provider": "openai"},
    ) as set_key, \
         patch("app.services.cache_service.invalidate", side_effect=fake_invalidate), \
         patch("app.core.model_registry.clear_llm_cache_for_provider") as clear_cache:
        resp = client.put(
            "/api/v1/models/api-keys/openai",
            json={"api_key": "sk-test-1234"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "saved"
    set_key.assert_called_once()
    clear_cache.assert_called_once_with("openai")


def test_upsert_api_key_400_on_value_error(client):
    with patch(
        "app.services.user_api_key_service.set_user_api_key",
        side_effect=ValueError("unknown provider"),
    ):
        resp = client.put(
            "/api/v1/models/api-keys/bogus",
            json={"api_key": "sk-test"},
        )
    assert resp.status_code == 400


def test_delete_api_key_reports_status(client):
    async def fake_invalidate(*_names):
        return None

    with patch(
        "app.services.user_api_key_service.delete_user_api_key", return_value=True,
    ), patch("app.services.cache_service.invalidate", side_effect=fake_invalidate), \
       patch("app.core.model_registry.clear_llm_cache_for_provider"):
        resp = client.delete("/api/v1/models/api-keys/openai")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


# ── /models/ping ──────────────────────────────────────────────────────────


def test_ping_models_returns_one_result_per_profile(client, monkeypatch):
    """P6-L: ping iterates ``_get_all_profiles()``, not the deleted MODEL_PROFILES."""
    fake_profiles = {"p1": object(), "p2": object()}
    monkeypatch.setattr(model_runtime_mod, "_get_all_profiles", lambda: fake_profiles)

    async def fake_ping(pid, user_id=None):
        return {"profile_id": pid, "ok": True, "latency_ms": 1}

    monkeypatch.setattr(model_runtime_mod, "_ping_one", fake_ping)

    resp = client.post("/api/v1/models/ping")
    assert resp.status_code == 200
    body = resp.json()
    ids = sorted(r["profile_id"] for r in body["results"])
    assert ids == ["p1", "p2"]
    assert all(r["ok"] for r in body["results"])
