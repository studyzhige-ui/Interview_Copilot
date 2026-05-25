"""Reverse-proxy IP rewrite tests.

When the app is behind nginx / ALB / CloudFront, every request's
``request.client.host`` collapses to the proxy IP unless we
explicitly install ``ProxyHeadersMiddleware``. That collapse turns
slowapi's per-IP rate-limit into a per-deploy rate-limit (one
attacker burns the 5/min login quota for every legitimate user)
and breaks the IP-lockout in ``verification_code_service``.

These tests pin the contract:

  1. With ``TRUSTED_PROXIES`` empty, ``client.host`` is the socket
     peer (dev behaviour, no rewrite).
  2. With the socket peer in the trust list AND an X-Forwarded-For
     header, ``client.host`` is rewritten to the real client.
  3. With an UNTRUSTED socket peer, X-Forwarded-For is ignored —
     attackers can't spoof their source IP by sending the header
     themselves.

(3) is the security-load-bearing case. ProxyHeadersMiddleware only
trusts XFF from peers listed in ``trusted_hosts``. If we were to
parse XFF unconditionally, an attacker could just set
``X-Forwarded-For: 1.2.3.4`` and bypass rate-limit.
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


def _echo_app(trusted_hosts: list[str] | None) -> FastAPI:
    """Build a minimal FastAPI that echoes ``request.client.host``.

    ``trusted_hosts=None`` skips the middleware entirely (mirrors the
    main.py branch where TRUSTED_PROXIES is empty).
    """
    app = FastAPI()
    if trusted_hosts is not None:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_hosts)

    @app.get("/whoami")
    def whoami(request: Request) -> dict[str, str | None]:
        return {"client_host": request.client.host if request.client else None}

    return app


def test_no_middleware_returns_socket_peer():
    """Default dev mode: TRUSTED_PROXIES empty → no middleware →
    ``client.host`` is the socket peer regardless of X-Forwarded-For."""
    app = _echo_app(trusted_hosts=None)
    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"X-Forwarded-For": "1.2.3.4"})
    # TestClient defaults the socket peer to "testclient" — the
    # important assertion is that the spoofed XFF was IGNORED.
    assert resp.json()["client_host"] != "1.2.3.4"


def test_trusted_proxy_rewrites_from_xff():
    """Production-shape: socket peer is in trust list, X-Forwarded-For
    has the real client. ``client.host`` must reflect the real client."""
    # TestClient uses "testclient" as the simulated peer. Trust it so the
    # middleware honors the XFF header.
    app = _echo_app(trusted_hosts=["testclient"])
    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"X-Forwarded-For": "203.0.113.42"})
    assert resp.json()["client_host"] == "203.0.113.42"


def test_untrusted_peer_ignores_xff():
    """Security-critical: if the immediate peer is NOT in trust list,
    the XFF header must be ignored — otherwise any attacker can
    spoof their source IP by sending the header themselves and
    bypass per-IP rate-limit + lockout."""
    # Trust only an IP that does NOT match TestClient's simulated
    # peer ("testclient"). The middleware should refuse to honor
    # the XFF from this peer.
    app = _echo_app(trusted_hosts=["10.0.0.1"])
    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"X-Forwarded-For": "1.2.3.4"})
    # Spoofed XFF ignored → client.host stays as the socket peer.
    assert resp.json()["client_host"] != "1.2.3.4"


def test_xff_chain_picks_rightmost_hop():
    """uvicorn's ProxyHeadersMiddleware walks X-Forwarded-For
    RIGHT-TO-LEFT and returns the first UNTRUSTED entry — i.e. the
    rightmost hop that isn't itself one of our known proxies. For
    the common single-layer deploy where only the immediate peer is
    in ``trusted_hosts``, this collapses to "rightmost entry of XFF".

    Pinning the behaviour so a silent uvicorn upgrade doesn't quietly
    break the rate-limit key.

    **Deploy caveat**: correct for SINGLE-LAYER proxy
    (nginx -> backend). For MULTI-LAYER proxy
    (Cloudflare -> nginx -> backend), nginx must rewrite XFF to
    contain only the real client IP (e.g. ``proxy_set_header
    X-Forwarded-For $remote_addr;``), otherwise the rightmost XFF
    entry is nginx itself. If you sit behind a CDN, do NOT use
    ``$proxy_add_x_forwarded_for`` in nginx — that APPENDS to the
    chain and leaves the rightmost = nginx itself.
    """
    app = _echo_app(trusted_hosts=["testclient"])
    with TestClient(app) as client:
        resp = client.get(
            "/whoami",
            headers={"X-Forwarded-For": "198.51.100.7, 192.0.2.1, 10.0.0.5"},
        )
    # Rightmost entry — uvicorn's chosen semantics.
    assert resp.json()["client_host"] == "10.0.0.5"
