"""API tests for the per-user provider settings endpoints (P6-M).

Covers:
  - GET  /models/providers          — list-all returns every PROVIDERS entry
  - GET  /models/providers/{p}      — single entry; 404 for unknown
  - PATCH /models/providers/{p}     — upsert + Pydantic validation
  - DELETE /models/providers/{p}    — revert to defaults

Security-critical assertions:
  - api_base_override SSRF check (private IP rejected, http:// rejected)
  - extra_headers_json schema + reserved-name blocklist (Authorization etc.)
  - 4xx returns instead of 500 on bad input
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import model_runtime as model_runtime_mod
from app.core.security import get_current_user
from app.services.model_sources.providers import PROVIDERS


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


# ── GET /models/providers ──────────────────────────────────────────────


def test_list_providers_returns_every_provider(client, monkeypatch):
    """Frontend renders both enabled + opt-in cards from this one call."""
    # Stub the resolver to avoid hitting the real DB.
    from app.services.user_provider_settings_service import ResolvedProviderSettings

    def fake_resolve_all(user_id, **_kw):
        return [
            ResolvedProviderSettings(
                provider=pid,
                display_label=d.display_label,
                icon_slug=d.icon_slug,
                enabled=d.enabled_by_default,
                has_user_row=False,
                api_base=d.default_api_base,
                api_base_override=None,
                organization_id=None,
                extra_headers_json=None,
                api_key_env=d.api_key_env,
                has_user_api_key=False,
            )
            for pid, d in PROVIDERS.items()
        ]
    monkeypatch.setattr(
        "app.services.user_provider_settings_service.resolve_all_provider_settings",
        fake_resolve_all,
    )
    resp = client.get("/api/v1/models/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    returned_ids = {p["provider"] for p in body["providers"]}
    assert returned_ids == set(PROVIDERS.keys())
    # Default-enabled flag flows through.
    for entry in body["providers"]:
        d = PROVIDERS[entry["provider"]]
        assert entry["enabled"] == d.enabled_by_default


# ── GET /models/providers/{p} ─────────────────────────────────────────


def test_get_single_provider_404_when_unknown(client):
    resp = client.get("/api/v1/models/providers/imaginary_corp")
    assert resp.status_code == 404


def test_get_single_provider_returns_shape(client, monkeypatch):
    from app.services.user_provider_settings_service import ResolvedProviderSettings

    def fake_resolve(user_id, provider, **_kw):
        if provider not in PROVIDERS:
            return None
        d = PROVIDERS[provider]
        return ResolvedProviderSettings(
            provider=provider,
            display_label=d.display_label,
            icon_slug=d.icon_slug,
            enabled=True,
            has_user_row=False,
            api_base=d.default_api_base,
            api_base_override=None,
            organization_id=None,
            extra_headers_json=None,
            api_key_env=d.api_key_env,
            has_user_api_key=False,
        )
    monkeypatch.setattr(
        "app.services.user_provider_settings_service.resolve_provider_settings",
        fake_resolve,
    )
    resp = client.get("/api/v1/models/providers/openai")
    assert resp.status_code == 200
    body = resp.json()["provider"]
    assert body["provider"] == "openai"
    assert body["api_base"] == PROVIDERS["openai"].default_api_base


# ── PATCH /models/providers/{p}: SSRF + schema validation ─────────────


def test_patch_rejects_http_api_base(client):
    """HTTPS required — http:// would leak the user's API key in clear."""
    resp = client.patch(
        "/api/v1/models/providers/openai",
        json={"api_base_override": "http://my-proxy.example.com/v1"},
    )
    assert resp.status_code == 422  # Pydantic validation
    detail = resp.json()["detail"][0]["msg"]
    assert "scheme not allowed" in detail or "api_base rejected" in detail


def test_patch_rejects_private_api_base(client):
    """SSRF guard: a host resolving to RFC1918 must be refused."""
    import socket

    fake_dns = [(0, 0, 0, "", ("10.0.0.5", 0))]
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=fake_dns):
        resp = client.patch(
            "/api/v1/models/providers/openai",
            json={"api_base_override": "https://internal.corp.example.com/v1"},
        )
    assert resp.status_code == 422
    assert "address space" in resp.json()["detail"][0]["msg"]


def test_patch_rejects_metadata_endpoint(client):
    """169.254.169.254 (AWS/GCP/Azure metadata) → blocked."""
    fake_dns = [(0, 0, 0, "", ("169.254.169.254", 0))]
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=fake_dns):
        resp = client.patch(
            "/api/v1/models/providers/openai",
            json={"api_base_override": "https://attacker.example.com/v1"},
        )
    assert resp.status_code == 422
    assert "address space" in resp.json()["detail"][0]["msg"]


def test_patch_rejects_extra_headers_reserved_name(client):
    """Authorization / Cookie / Host / anthropic-version are system-controlled."""
    resp = client.patch(
        "/api/v1/models/providers/openai",
        json={"extra_headers_json": '{"Authorization": "Bearer evil"}'},
    )
    assert resp.status_code == 422
    assert "system-controlled" in resp.json()["detail"][0]["msg"]


def test_patch_rejects_extra_headers_too_many(client):
    big = '{' + ",".join(f'"H{i}":"v"' for i in range(11)) + '}'
    resp = client.patch(
        "/api/v1/models/providers/openai",
        json={"extra_headers_json": big},
    )
    assert resp.status_code == 422
    assert "too many extra headers" in resp.json()["detail"][0]["msg"]


def test_patch_rejects_extra_headers_malformed_json(client):
    resp = client.patch(
        "/api/v1/models/providers/openai",
        json={"extra_headers_json": "not a json object"},
    )
    assert resp.status_code == 422


def test_patch_rejects_extra_headers_non_object(client):
    resp = client.patch(
        "/api/v1/models/providers/openai",
        json={"extra_headers_json": '["a", "b"]'},
    )
    assert resp.status_code == 422
    assert "object" in resp.json()["detail"][0]["msg"]


def test_patch_rejects_organization_with_control_chars(client):
    resp = client.patch(
        "/api/v1/models/providers/openai",
        json={"organization_id": "org\x07-evil"},
    )
    assert resp.status_code == 422
    assert "control characters" in resp.json()["detail"][0]["msg"]


def test_patch_returns_404_on_unknown_provider(client, monkeypatch):
    """Pydantic body accepts the JSON, but the service rejects unknown provider."""
    fake_dns = [(0, 0, 0, "", ("8.8.8.8", 0))]
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=fake_dns):
        resp = client.patch(
            "/api/v1/models/providers/no_such_vendor",
            json={"api_base_override": "https://valid-public.example.com/v1"},
        )
    assert resp.status_code == 404


def test_patch_happy_path_saves_and_invalidates(client, monkeypatch):
    """Valid override persists; LLM client cache + 60s wrapper get cleared."""
    from app.services.user_provider_settings_service import ResolvedProviderSettings

    saved = {}
    def fake_upsert(user_id, provider, patch_obj, **_kw):
        saved["user_id"] = user_id
        saved["provider"] = provider
        saved["enabled"] = patch_obj.enabled
        saved["api_base"] = patch_obj.api_base_override
        d = PROVIDERS[provider]
        return ResolvedProviderSettings(
            provider=provider, display_label=d.display_label,
            icon_slug=d.icon_slug, enabled=True, has_user_row=True,
            api_base=patch_obj.api_base_override or d.default_api_base,
            api_base_override=patch_obj.api_base_override,
            organization_id=None, extra_headers_json=None,
            api_key_env=d.api_key_env, has_user_api_key=False,
        )

    clear_calls = {"n": 0, "provider": None}
    def fake_clear(provider):
        clear_calls["n"] += 1
        clear_calls["provider"] = provider

    async def fake_invalidate(*_a, **_kw):
        return None

    monkeypatch.setattr(
        "app.services.user_provider_settings_service.upsert_settings", fake_upsert,
    )
    monkeypatch.setattr(
        "app.core.model_registry.clear_llm_cache_for_provider", fake_clear,
    )
    fake_dns = [(0, 0, 0, "", ("8.8.8.8", 0))]
    with patch("app.core.ssrf.socket.getaddrinfo", return_value=fake_dns), \
         patch("app.services.cache_service.invalidate", side_effect=fake_invalidate):
        resp = client.patch(
            "/api/v1/models/providers/openai",
            json={
                "enabled": True,
                "api_base_override": "https://my-enterprise.example.com/v1",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "saved"
    assert body["provider"]["api_base_override"] == "https://my-enterprise.example.com/v1"
    assert saved["api_base"] == "https://my-enterprise.example.com/v1"
    assert clear_calls["provider"] == "openai", "must clear cached LLM client"


def test_patch_clear_via_empty_string(client, monkeypatch):
    """Sending ``api_base_override=""`` clears the override — not a validation error."""
    from app.services.user_provider_settings_service import ResolvedProviderSettings

    captured = {}
    def fake_upsert(user_id, provider, patch_obj, **_kw):
        captured["api_base"] = patch_obj.api_base_override
        d = PROVIDERS[provider]
        return ResolvedProviderSettings(
            provider=provider, display_label=d.display_label,
            icon_slug=d.icon_slug, enabled=True, has_user_row=True,
            api_base=d.default_api_base, api_base_override=None,
            organization_id=None, extra_headers_json=None,
            api_key_env=d.api_key_env, has_user_api_key=False,
        )

    async def fake_invalidate(*_a, **_kw):
        return None

    monkeypatch.setattr(
        "app.services.user_provider_settings_service.upsert_settings", fake_upsert,
    )
    monkeypatch.setattr("app.core.model_registry.clear_llm_cache_for_provider", lambda *_: None)
    with patch("app.services.cache_service.invalidate", side_effect=fake_invalidate):
        resp = client.patch(
            "/api/v1/models/providers/openai",
            json={"api_base_override": ""},
        )
    assert resp.status_code == 200
    assert captured["api_base"] == ""  # service receives "" → translates to NULL


# ── DELETE /models/providers/{p} ──────────────────────────────────────


def test_delete_provider_settings_clears_cache(client, monkeypatch):
    clear_calls = {"n": 0}
    monkeypatch.setattr(
        "app.services.user_provider_settings_service.delete_settings",
        lambda *_a, **_kw: True,
    )
    monkeypatch.setattr(
        "app.core.model_registry.clear_llm_cache_for_provider",
        lambda *_: clear_calls.__setitem__("n", clear_calls["n"] + 1),
    )
    async def fake_invalidate(*_a, **_kw):
        return None

    with patch("app.services.cache_service.invalidate", side_effect=fake_invalidate):
        resp = client.delete("/api/v1/models/providers/openai")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert clear_calls["n"] == 1


def test_delete_provider_settings_noop_when_no_row(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.user_provider_settings_service.delete_settings",
        lambda *_a, **_kw: False,
    )
    monkeypatch.setattr(
        "app.core.model_registry.clear_llm_cache_for_provider", lambda *_: None,
    )
    async def fake_invalidate(*_a, **_kw):
        return None

    with patch("app.services.cache_service.invalidate", side_effect=fake_invalidate):
        resp = client.delete("/api/v1/models/providers/openai")
    assert resp.status_code == 200
    assert resp.json()["status"] == "noop"
