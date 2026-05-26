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
from app.services.model_catalog_service import _fetch_one_provider


def _install_mock_transport(monkeypatch, response: httpx.Response | Exception):
    """Replace httpx.AsyncClient with one whose transport returns ``response``.

    If ``response`` is an Exception subclass instance, the transport raises
    it (simulating a connection error).
    """
    def handler(request: httpx.Request) -> httpx.Response:
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
