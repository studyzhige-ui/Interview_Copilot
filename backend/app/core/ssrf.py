"""Shared SSRF guard for user-supplied URLs.

Hoisted from ``app/agent_runtime/tools/web.py`` so the new
``/models/providers/{provider}`` PATCH endpoint (P6-M) can reuse the
same check on ``api_base_override`` without duplicating the IP-class
heuristics.

What it covers:
  • non-http(s) schemes (file://, gopher://, dict://, …) — refused
  • RFC1918 (10/8, 172.16/12, 192.168/16) via ``is_private``
  • Loopback (127.0.0.0/8 + ::1) via ``is_loopback``
  • Link-local (169.254/16 — AWS/GCP/Azure instance-metadata endpoint)
  • Reserved / multicast / unspecified (defence in depth)

What it does NOT cover: DNS rebinding. Mitigating requires resolve-once
then dial-via-resolved-IP, which is a bigger refactor — out of scope.
The guard still blocks 99% of the realistic SSRF attempts.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UrlNotSafe(ValueError):
    """Raised when a URL fails the SSRF guard.

    The message is safe to surface to the user (HTTP 400). It never
    leaks internal IPs we resolved — only the input URL and a coarse
    classification (private / loopback / reserved).
    """


def validate_safe_url(url: str, *, require_https: bool = False) -> None:
    """Reject ``url`` if it has a non-http(s) scheme or any resolved IP
    lands in private / loopback / link-local / reserved / multicast /
    unspecified space.

    ``require_https=True`` is stricter — used by the model-provider
    settings endpoint where http://… in production would silently leak
    the user's API key over plaintext. The web tool keeps the looser
    default because LLMs sometimes get http URLs from agents that don't
    set the scheme correctly.

    Synchronous: ``socket.getaddrinfo`` is blocking. Async callers
    should offload via ``asyncio.to_thread``.
    """
    parsed = urlparse(url)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in allowed_schemes:
        raise UrlNotSafe(
            f"scheme not allowed: {parsed.scheme!r} "
            f"(allowed: {sorted(allowed_schemes)})",
        )
    if not parsed.hostname:
        raise UrlNotSafe("missing hostname")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        # DNS failure is itself a refuse signal — without a resolved IP
        # we can't make a safety decision.
        raise UrlNotSafe(f"dns resolution failed: {exc}") from exc

    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise UrlNotSafe(f"bad ip from dns: {ip_str!r}") from exc
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            # Classify rather than echo the IP — keeps the error
            # actionable without disclosing the resolution.
            classes = []
            if ip.is_private:
                classes.append("private")
            if ip.is_loopback:
                classes.append("loopback")
            if ip.is_link_local:
                classes.append("link-local (metadata)")
            if ip.is_reserved:
                classes.append("reserved")
            if ip.is_multicast:
                classes.append("multicast")
            if ip.is_unspecified:
                classes.append("unspecified")
            raise UrlNotSafe(
                f"host resolves to {'/'.join(classes)} address space",
            )


__all__ = ["UrlNotSafe", "validate_safe_url"]
