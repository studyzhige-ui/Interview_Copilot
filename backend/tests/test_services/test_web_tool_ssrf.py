"""SSRF guard tests for the ``read_url`` agent tool.

The agent is reachable via prompt injection — a user can paste text
asking the LLM to fetch ``http://169.254.169.254/...`` and the LLM
will obediently call ``read_url`` with that URL. Without the guard
this would hit cloud-metadata endpoints and surface IAM credentials.

These tests cover the pure validator (``_validate_safe_url``) and
the handler integration (the handler must refuse via the validator
BEFORE opening any TCP socket, and must re-validate redirect
targets so an attacker can't bounce out of a public domain into a
private one via a 302).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


# ── _validate_safe_url ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected_substr",
    [
        # Schemes other than http(s) are rejected categorically.
        ("file:///etc/passwd", "scheme not allowed"),
        ("gopher://internal", "scheme not allowed"),
        ("dict://localhost:11211/", "scheme not allowed"),
        ("javascript:alert(1)", "scheme not allowed"),
        # No hostname (e.g. ``http://`` alone).
        ("http://", "missing hostname"),
    ],
)
def test_validator_rejects_bad_schemes(url, expected_substr):
    from app.agent_runtime.tools.web import _UrlNotSafe, _validate_safe_url

    with pytest.raises(_UrlNotSafe, match=expected_substr):
        _validate_safe_url(url)


@pytest.mark.parametrize(
    "ip, label",
    [
        # AWS / GCP / Azure cloud-metadata endpoints all live in
        # 169.254/16 (RFC 3927 link-local). The single most important
        # entry on this list — getting this address means IAM creds.
        ("169.254.169.254", "link-local"),
        # RFC1918 private space.
        ("10.0.0.5", "private"),
        ("172.16.5.10", "private"),
        ("192.168.1.1", "private"),
        # Loopback.
        ("127.0.0.1", "loopback"),
        # IPv6 loopback + link-local + ULA.
        ("::1", "loopback"),
        ("fe80::1", "link-local"),
        ("fc00::1", "private"),
        # Unspecified — sometimes accidentally lets you bind to all
        # interfaces and reach loopback services.
        ("0.0.0.0", "unspecified"),
    ],
)
def test_validator_rejects_dangerous_ips(ip, label):
    """Mock DNS so the hostname resolves to a dangerous IP. The
    validator should refuse before any TCP socket opens."""
    from app.agent_runtime.tools.web import _UrlNotSafe, _validate_safe_url

    fake_dns = [(0, 0, 0, "", (ip, 0))]
    with patch("app.agent_runtime.tools.web.socket.getaddrinfo",
               return_value=fake_dns):
        with pytest.raises(_UrlNotSafe, match="private|loopback|reserved"):
            _validate_safe_url(f"http://attacker-controlled.example.com/x")
    # ``label`` is documentation-only — the regex above covers any of
    # the categorical refusal substrings.
    assert label  # noqa: PT017 — used by the test ID, asserted via match


def test_validator_accepts_public_ip():
    """A public IP (8.8.8.8) must pass — otherwise the tool is useless."""
    from app.agent_runtime.tools.web import _validate_safe_url

    fake_dns = [(0, 0, 0, "", ("8.8.8.8", 0))]
    with patch("app.agent_runtime.tools.web.socket.getaddrinfo",
               return_value=fake_dns):
        # Should not raise.
        _validate_safe_url("https://dns.google/")


def test_validator_rejects_when_any_resolved_ip_is_dangerous():
    """Multi-A-record defense: if a hostname resolves to BOTH a public
    and a private IP (dual-homed host, or attacker abusing
    multi-record DNS), refuse on the most dangerous one."""
    from app.agent_runtime.tools.web import _UrlNotSafe, _validate_safe_url

    fake_dns = [
        (0, 0, 0, "", ("8.8.8.8", 0)),
        (0, 0, 0, "", ("10.0.0.1", 0)),
    ]
    with patch("app.agent_runtime.tools.web.socket.getaddrinfo",
               return_value=fake_dns):
        with pytest.raises(_UrlNotSafe):
            _validate_safe_url("http://multihomed.example.com/")


def test_validator_refuses_when_dns_fails():
    """A DNS failure is itself a refuse signal — we can't make a
    safety decision without a resolved IP, and silently letting the
    request through would defeat the guard."""
    import socket as real_socket

    from app.agent_runtime.tools.web import _UrlNotSafe, _validate_safe_url

    with patch(
        "app.agent_runtime.tools.web.socket.getaddrinfo",
        side_effect=real_socket.gaierror("no such host"),
    ):
        with pytest.raises(_UrlNotSafe, match="dns resolution failed"):
            _validate_safe_url("https://nonexistent.invalid/")


# ── handler integration ─────────────────────────────────────────────────


def test_handler_returns_error_for_unsafe_scheme():
    """Handler must not raise; it must return the standard tool-error
    payload so the agent observes the refusal and adapts."""
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.web import _read_url_handler, ReadUrlArgs

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    args = ReadUrlArgs(url="file:///etc/passwd")
    result = asyncio.run(_read_url_handler(args, ctx))
    assert "error" in result
    assert "refused" in result["error"]
    # URL is echoed so the agent (and the user-visible tool card) sees
    # what was attempted.
    assert result["url"] == "file:///etc/passwd"


def test_handler_returns_error_for_cloud_metadata_ip():
    """The single most important regression: agent prompt-injected
    into calling read_url on 169.254.169.254 must be refused."""
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.web import _read_url_handler, ReadUrlArgs

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    args = ReadUrlArgs(url="http://169.254.169.254/latest/meta-data/iam/")
    fake_dns = [(0, 0, 0, "", ("169.254.169.254", 0))]
    with patch("app.agent_runtime.tools.web.socket.getaddrinfo",
               return_value=fake_dns):
        result = asyncio.run(_read_url_handler(args, ctx))
    assert "error" in result
    assert "refused" in result["error"]


def test_handler_refuses_redirect_to_private_host():
    """An attacker can serve a 302 from a public domain that points
    at a private one. ``follow_redirects=False`` + manual per-hop
    re-validation must catch this."""
    import httpx

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.web import _read_url_handler, ReadUrlArgs

    # Public for the initial validate, private for the redirect target.
    # NB: do NOT use 203.0.113.x — that's RFC 5737 TEST-NET-3, which
    # ``is_reserved`` correctly refuses. Use a real public IP for the
    # initial-hop fixture.
    dns_lookups = {
        "public.example.com": [(0, 0, 0, "", ("8.8.8.8", 0))],
        "internal.local": [(0, 0, 0, "", ("10.0.0.5", 0))],
    }

    def fake_getaddrinfo(host, *_a, **_kw):
        return dns_lookups[host]

    # Fake httpx — first GET returns a 302 pointing at the private host.
    class _Resp:
        def __init__(self, status, url, headers=None, text=""):
            self.status_code = status
            self.url = url
            self.headers = headers or {}
            self.text = text

    async def fake_get(url, headers=None):  # noqa: ARG001
        return _Resp(
            302,
            url,
            headers={"location": "http://internal.local/secret"},
        )

    class _FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, headers=None):
            return await fake_get(url, headers)

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    args = ReadUrlArgs(url="http://public.example.com/page")
    with patch("app.agent_runtime.tools.web.socket.getaddrinfo",
               side_effect=fake_getaddrinfo):
        with patch.object(httpx, "AsyncClient", _FakeClient):
            result = asyncio.run(_read_url_handler(args, ctx))
    assert "error" in result
    assert "refused redirect" in result["error"]
