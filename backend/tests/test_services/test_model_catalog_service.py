"""Tests for the model-catalog discovery service.

Locks in the post-P6-H behaviour:

1.  ``_fetch_one_provider`` sorts vendor-supplied chat model ids
    newest-first, using ``created`` timestamps when present and a
    reverse-alpha fallback otherwise. The prior alphabetical sort put
    older ids (gpt-3.5-turbo, gpt-4) ahead of the latest releases
    (gpt-5.2), pushing the most-recent models off the visible portion
    of each vendor card.
2.  Non-chat models (embeddings, whisper, dall-e, etc.) are filtered
    out via the substring blocklist.
3.  Network / auth failures degrade silently to an empty list so a
    flaky vendor never breaks the catalog endpoint.

We use ``httpx.MockTransport`` and patch ``httpx.AsyncClient`` to use
it — this is the supported httpx test path and works regardless of
which internal method (``get`` vs ``request``) the SUT calls.
"""
from __future__ import annotations

import httpx
import pytest

from app.services import model_catalog_service
from app.services.model_catalog_service import (
    _auth_headers,
    _fetch_one_provider,
    _key,
    _resolve_api_key,
    discover_provider,
    invalidate_for_user_provider,
)


def _install_mock_transport(
    monkeypatch,
    response: httpx.Response | Exception,
    *,
    capture: dict | None = None,
):
    """Replace httpx.AsyncClient with one whose transport returns ``response``.

    If ``response`` is an Exception subclass instance, the transport raises
    it (simulating a connection error).

    Pass a ``capture`` dict to record the outgoing request (we use this to
    assert per-vendor auth header shape).
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["url"] = str(request.url)
            capture["headers"] = dict(request.headers)
        if isinstance(response, Exception):
            raise response
        return response

    transport = httpx.MockTransport(handler)
    real_cls = httpx.AsyncClient

    def factory(*args, **kwargs):  # noqa: ANN001
        # Force our transport in regardless of what the SUT passed.
        kwargs["transport"] = transport
        return real_cls(*args, **kwargs)

    monkeypatch.setattr(model_catalog_service.httpx, "AsyncClient", factory)


@pytest.mark.asyncio
async def test_fetch_sorts_by_created_desc(monkeypatch):
    """Ids with ``created`` timestamps come out newest-first regardless of name."""
    payload = {
        "data": [
            {"id": "gpt-4o",      "created": 1_700_000_000},
            {"id": "gpt-5.2",     "created": 1_900_000_000},  # newest
            {"id": "gpt-4.1",     "created": 1_750_000_000},
            {"id": "gpt-5",       "created": 1_850_000_000},
        ],
    }
    _install_mock_transport(monkeypatch, httpx.Response(200, json=payload))

    ids = await _fetch_one_provider("openai", "https://api.openai.com/v1", "sk-x")
    assert ids == ["gpt-5.2", "gpt-5", "gpt-4.1", "gpt-4o"]


@pytest.mark.asyncio
async def test_fetch_reverse_alpha_when_no_timestamp(monkeypatch):
    """Without ``created`` we fall back to reverse-alpha — which still
    lands on newest-first for every vendor's actual id convention."""
    payload = {
        "data": [
            {"id": "gpt-4o"},
            {"id": "gpt-5"},
            {"id": "gpt-5.2"},
            {"id": "gpt-4.1"},
        ],
    }
    _install_mock_transport(monkeypatch, httpx.Response(200, json=payload))

    ids = await _fetch_one_provider("openai", "https://api.openai.com/v1", "sk-x")
    assert ids[0] == "gpt-5.2", ids
    assert ids[1] == "gpt-5", ids
    # GPT-4o and GPT-4.1 are both older; relative order is a tie-break
    # detail, but both must come after the GPT-5 family.
    assert set(ids[2:]) == {"gpt-4o", "gpt-4.1"}


@pytest.mark.asyncio
async def test_fetch_filters_non_chat_models(monkeypatch):
    """Embedding / whisper / dall-e ids never make it into the dropdown."""
    payload = {
        "data": [
            {"id": "gpt-5.2", "created": 1_900_000_000},
            {"id": "text-embedding-3-small", "created": 1_800_000_000},
            {"id": "whisper-1", "created": 1_600_000_000},
            {"id": "dall-e-3", "created": 1_700_000_000},
            {"id": "tts-1", "created": 1_650_000_000},
        ],
    }
    _install_mock_transport(monkeypatch, httpx.Response(200, json=payload))

    ids = await _fetch_one_provider("openai", "https://api.openai.com/v1", "sk-x")
    assert ids == ["gpt-5.2"]


@pytest.mark.asyncio
async def test_fetch_swallows_network_error(monkeypatch):
    """Network blip → empty list, never raises (catalog endpoint must not 500)."""
    _install_mock_transport(monkeypatch, httpx.ConnectError("boom"))

    ids = await _fetch_one_provider("openai", "https://api.openai.com/v1", "sk-x")
    assert ids == []


@pytest.mark.asyncio
async def test_fetch_swallows_auth_error(monkeypatch):
    """401 → empty list (user just hasn't configured the key for this vendor)."""
    _install_mock_transport(
        monkeypatch, httpx.Response(401, json={"error": "unauthorized"}),
    )

    ids = await _fetch_one_provider("openai", "https://api.openai.com/v1", "sk-x")
    assert ids == []


@pytest.mark.asyncio
async def test_fetch_handles_anthropic_iso_timestamp(monkeypatch):
    """Anthropic exposes ``created_at`` as ISO-8601 (not a Unix int).

    Without ISO parsing, reverse-alpha is the only signal — and reverse-alpha
    gives the wrong winner here because ``sonnet`` > ``opus`` > ``3`` under
    plain string compare. With ISO parsing the timestamp wins and Opus 4.7
    (the actual flagship) floats to the top.
    """
    payload = {
        "data": [
            {"id": "claude-3-7-sonnet-20250219",  "created_at": "2025-02-19T00:00:00Z"},
            {"id": "claude-sonnet-4-6-20251015",  "created_at": "2025-10-15T00:00:00Z"},
            {"id": "claude-opus-4-7-20251115",    "created_at": "2025-11-15T00:00:00Z"},  # newest
            {"id": "claude-haiku-4-5-20251001",   "created_at": "2025-10-01T00:00:00Z"},
        ],
    }
    _install_mock_transport(monkeypatch, httpx.Response(200, json=payload))

    ids = await _fetch_one_provider(
        "anthropic", "https://api.anthropic.com/v1", "sk-ant-x",
    )
    # Newest-first by timestamp regardless of where tier-name alpha-sorts:
    assert ids == [
        "claude-opus-4-7-20251115",
        "claude-sonnet-4-6-20251015",
        "claude-haiku-4-5-20251001",
        "claude-3-7-sonnet-20250219",
    ]


@pytest.mark.asyncio
async def test_fetch_dedupes_ids(monkeypatch):
    """If a vendor returns the same id twice we surface it once."""
    payload = {
        "data": [
            {"id": "gpt-5.2", "created": 1_900_000_000},
            {"id": "gpt-5.2", "created": 1_899_000_000},
            {"id": "gpt-5",   "created": 1_850_000_000},
        ],
    }
    _install_mock_transport(monkeypatch, httpx.Response(200, json=payload))

    ids = await _fetch_one_provider("openai", "https://api.openai.com/v1", "sk-x")
    assert ids == ["gpt-5.2", "gpt-5"]


# ── P6-I auth header per vendor ──────────────────────────────────────────


def test_auth_headers_openai_uses_bearer():
    h = _auth_headers("openai", "sk-test")
    assert h == {"Authorization": "Bearer sk-test"}


def test_auth_headers_anthropic_uses_x_api_key_and_version():
    """Anthropic rejects Bearer — discovery would 401 silently and Claude
    would be missing from the catalog. Must use x-api-key + version pin."""
    h = _auth_headers("anthropic", "sk-ant-test")
    assert h == {
        "x-api-key": "sk-ant-test",
        "anthropic-version": "2023-06-01",
    }
    # Crucially, NO Authorization header — Anthropic ignores it but a
    # future change that adds it back would be a regression worth catching.
    assert "Authorization" not in h


def test_auth_headers_other_providers_use_bearer():
    for prov in ("deepseek", "google", "qwen", "moonshot", "zhipu", "xiaomi", "nvidia"):
        h = _auth_headers(prov, "k")
        assert h == {"Authorization": "Bearer k"}, prov


@pytest.mark.asyncio
async def test_fetch_sends_anthropic_headers_on_the_wire(monkeypatch):
    """End-to-end: the GET to api.anthropic.com/v1/models carries the
    x-api-key + anthropic-version headers (and no Bearer)."""
    captured: dict = {}
    payload = {"data": [{"id": "claude-opus-4-7", "created_at": "2025-11-15T00:00:00Z"}]}
    _install_mock_transport(
        monkeypatch, httpx.Response(200, json=payload), capture=captured,
    )

    ids = await _fetch_one_provider(
        "anthropic", "https://api.anthropic.com/v1", "sk-ant-secret",
    )
    assert ids == ["claude-opus-4-7"]
    # httpx lowercases header names in the request log.
    assert captured["headers"].get("x-api-key") == "sk-ant-secret"
    assert captured["headers"].get("anthropic-version") == "2023-06-01"
    assert "authorization" not in captured["headers"]


# ── P6-I user_id key resolution + per-user cache scope ───────────────────


def test_resolve_api_key_prefers_user_row_over_env(monkeypatch):
    """If the user configured a key in-app, that wins over .env."""
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    def fake_user_lookup(uid, prov, **kw):  # noqa: ANN001
        assert uid == "alice"
        assert prov == "openai"
        return "user-stored-key"

    import app.services.user_api_key_service as svc
    monkeypatch.setattr(svc, "get_user_api_key_plaintext", fake_user_lookup)

    assert _resolve_api_key("openai", "OPENAI_API_KEY", user_id="alice") == "user-stored-key"


def test_resolve_api_key_falls_back_to_env_when_user_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    def fake_user_lookup(uid, prov, **kw):  # noqa: ANN001
        return None  # no row for this user

    import app.services.user_api_key_service as svc
    monkeypatch.setattr(svc, "get_user_api_key_plaintext", fake_user_lookup)

    assert _resolve_api_key("openai", "OPENAI_API_KEY", user_id="bob") == "env-key"


def test_resolve_api_key_returns_empty_when_neither_set(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_user_lookup(uid, prov, **kw):  # noqa: ANN001
        return None

    import app.services.user_api_key_service as svc
    monkeypatch.setattr(svc, "get_user_api_key_plaintext", fake_user_lookup)

    assert _resolve_api_key("openai", "OPENAI_API_KEY", user_id="carol") == ""


def test_resolve_api_key_no_user_id_uses_env_only(monkeypatch):
    """Global / startup contexts (no user_id) skip the DB lookup entirely."""
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    def boom(uid, prov, **kw):  # noqa: ANN001
        raise AssertionError("user lookup must not be called when user_id is None")

    import app.services.user_api_key_service as svc
    monkeypatch.setattr(svc, "get_user_api_key_plaintext", boom)

    assert _resolve_api_key("openai", "OPENAI_API_KEY", user_id=None) == "env-key"


def test_cache_key_is_per_user():
    """Different users must get different cache buckets — otherwise user A's
    preview-tier /v1/models response leaks into user B's catalog view."""
    a = _key("openai", "alice")
    b = _key("openai", "bob")
    g = _key("openai", None)
    assert a != b
    assert a != g
    assert b != g
    # All under the same prefix so invalidate_all (which scans by prefix)
    # still purges every variant in one shot.
    for k in (a, b, g):
        assert k.startswith("model_catalog:v2:")


@pytest.mark.asyncio
async def test_discover_provider_uses_user_stored_key_when_env_empty(monkeypatch):
    """The core bug this commit fixes: a user who only set their key
    through the UI (not .env) used to see zero discovered models because
    discover_provider only read os.getenv. Now it must resolve via
    user_api_keys first and successfully fetch /v1/models."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_user_lookup(uid, prov, **kw):  # noqa: ANN001
        return "sk-from-ui" if (uid == "alice" and prov == "openai") else None

    import app.services.user_api_key_service as svc
    monkeypatch.setattr(svc, "get_user_api_key_plaintext", fake_user_lookup)

    # Force discovery to skip Redis cache (Redis isn't connected in tests
    # anyway, but force_refresh makes the intent explicit).
    payload = {"data": [{"id": "gpt-5.5", "created": 2_000_000_000}]}
    captured: dict = {}
    _install_mock_transport(
        monkeypatch, httpx.Response(200, json=payload), capture=captured,
    )

    models = await discover_provider(
        "openai", "https://api.openai.com/v1", "OPENAI_API_KEY",
        user_id="alice", force_refresh=True,
    )

    assert [m.model for m in models] == ["gpt-5.5"]
    # And the wire-level Bearer used the user-stored key, NOT empty:
    assert captured["headers"].get("authorization") == "Bearer sk-from-ui"


@pytest.mark.asyncio
async def test_discover_provider_returns_empty_when_no_key_anywhere(monkeypatch):
    """No env + no user_api_keys row → no /v1/models call (avoids guaranteed 401)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_user_lookup(uid, prov, **kw):  # noqa: ANN001
        return None

    import app.services.user_api_key_service as svc
    monkeypatch.setattr(svc, "get_user_api_key_plaintext", fake_user_lookup)

    # If discovery DID call /v1/models, this transport would record it.
    captured: dict = {}
    _install_mock_transport(
        monkeypatch, httpx.Response(200, json={"data": []}), capture=captured,
    )

    models = await discover_provider(
        "openai", "https://api.openai.com/v1", "OPENAI_API_KEY",
        user_id="alice", force_refresh=True,
    )
    assert models == []
    # And we short-circuited before issuing the GET:
    assert captured == {}


# ── P6-I follow-ups: don't poison cache on empty + per-user invalidate ──


class _FakeRedis:
    """Minimal stand-in for the async Redis client. Tracks sets and deletes
    so tests can assert what the SUT cached / dropped without a live broker.
    """
    def __init__(self):
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):  # noqa: ANN001
        self.store[key] = value
        self.set_calls.append((key, value))
        return True

    async def delete(self, key):
        self.delete_calls.append(key)
        return 1 if self.store.pop(key, None) is not None else 0

    async def scan_iter(self, match=None, count=None):  # noqa: ANN001
        for k in list(self.store.keys()):
            yield k


@pytest.mark.asyncio
async def test_empty_fetch_result_is_not_cached(monkeypatch):
    """A transient 5xx / DNS failure must not poison the 24h cache.

    Pre-fix: any failure path returned [] and we cached the empty list,
    silently serving "no models" to that user for 24h even after the
    vendor recovered. Now the empty result skips the Redis write so the
    next call retries the vendor immediately.
    """
    fake = _FakeRedis()
    monkeypatch.setattr(model_catalog_service, "redis_client", fake)

    def fake_user_lookup(uid, prov, **kw):  # noqa: ANN001
        return "sk-x"

    import app.services.user_api_key_service as svc
    monkeypatch.setattr(svc, "get_user_api_key_plaintext", fake_user_lookup)

    # Simulate a vendor outage: 503 → _fetch_one_provider returns [].
    _install_mock_transport(monkeypatch, httpx.Response(503, json={"error": "down"}))

    models = await discover_provider(
        "openai", "https://api.openai.com/v1", "OPENAI_API_KEY",
        user_id="alice", force_refresh=True,
    )
    assert models == []
    # Critically: nothing was written to Redis. The next call will hit
    # the vendor again instead of serving an empty cached result.
    assert fake.set_calls == []
    assert fake.store == {}


@pytest.mark.asyncio
async def test_non_empty_fetch_result_is_still_cached(monkeypatch):
    """Sanity check: the empty-skip logic doesn't accidentally also skip
    successful fetches."""
    fake = _FakeRedis()
    monkeypatch.setattr(model_catalog_service, "redis_client", fake)

    def fake_user_lookup(uid, prov, **kw):  # noqa: ANN001
        return "sk-x"

    import app.services.user_api_key_service as svc
    monkeypatch.setattr(svc, "get_user_api_key_plaintext", fake_user_lookup)

    payload = {"data": [{"id": "gpt-5.5", "created": 2_000_000_000}]}
    _install_mock_transport(monkeypatch, httpx.Response(200, json=payload))

    models = await discover_provider(
        "openai", "https://api.openai.com/v1", "OPENAI_API_KEY",
        user_id="alice", force_refresh=True,
    )
    assert [m.model for m in models] == ["gpt-5.5"]
    # Cache write happened under the per-user key:
    assert len(fake.set_calls) == 1
    key, value = fake.set_calls[0]
    assert key == _key("openai", "alice")
    assert "gpt-5.5" in value


@pytest.mark.asyncio
async def test_invalidate_for_user_provider_drops_only_that_users_key(monkeypatch):
    """Key rotation must clear only the affected user/vendor entry,
    leaving other users' caches and other vendors for the same user intact.
    """
    fake = _FakeRedis()
    monkeypatch.setattr(model_catalog_service, "redis_client", fake)

    # Seed three entries: alice/openai, alice/anthropic, bob/openai.
    fake.store[_key("openai", "alice")] = '["gpt-5.5"]'
    fake.store[_key("anthropic", "alice")] = '["claude-opus-4-7"]'
    fake.store[_key("openai", "bob")] = '["gpt-4.1"]'

    ok = await invalidate_for_user_provider("alice", "openai")
    assert ok is True

    # Only alice/openai is gone:
    assert _key("openai", "alice") not in fake.store
    assert _key("anthropic", "alice") in fake.store
    assert _key("openai", "bob") in fake.store


@pytest.mark.asyncio
async def test_invalidate_for_user_provider_swallows_redis_error(monkeypatch):
    """A Redis outage during invalidation must not break the API-key
    upsert / delete flow that calls this — best-effort only."""
    class BrokenRedis:
        async def delete(self, key):
            raise RuntimeError("redis down")

    monkeypatch.setattr(model_catalog_service, "redis_client", BrokenRedis())

    ok = await invalidate_for_user_provider("alice", "openai")
    assert ok is False  # signal failure, but don't raise
