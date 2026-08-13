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

Callers that perform network I/O must use :func:`resolve_safe_url` and dial its
``connect_url``.  That pins the TCP connection to the exact address validated
here and closes the DNS-rebinding gap between validation and connection.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


class UrlNotSafe(ValueError):
    """Raised when a URL fails the SSRF guard.

    The message is safe to surface to the user (HTTP 400). It never
    leaks internal IPs we resolved — only the input URL and a coarse
    classification (private / loopback / reserved).
    """


@dataclass(frozen=True)
class ResolvedSafeUrl:
    original_url: str
    connect_url: str
    hostname: str
    host_header: str
    sni_hostname: str | None


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_safe_url(
    url: str,
    *,
    require_https: bool = False,
    allow_private: bool = False,
) -> ResolvedSafeUrl:
    """Validate and resolve one URL for resolve-once, dial-by-IP clients."""

    parsed = urlsplit(url)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in allowed_schemes:
        raise UrlNotSafe(
            f"scheme not allowed: {parsed.scheme!r} "
            f"(allowed: {sorted(allowed_schemes)})",
        )
    if not parsed.hostname:
        raise UrlNotSafe("missing hostname")
    if parsed.username is not None or parsed.password is not None:
        raise UrlNotSafe("URL userinfo is not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UrlNotSafe("invalid port") from exc

    try:
        infos = socket.getaddrinfo(
            parsed.hostname,
            port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UrlNotSafe(f"dns resolution failed: {exc}") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise UrlNotSafe("bad ip from dns") from exc
        if not allow_private and _is_forbidden_ip(ip):
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
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        raise UrlNotSafe("dns resolution returned no addresses")

    selected = addresses[0]
    ip_host = f"[{selected}]" if selected.version == 6 else str(selected)
    default_port = 443 if parsed.scheme == "https" else 80
    connect_netloc = ip_host if port in {None, default_port} else f"{ip_host}:{port}"
    host_header = (
        parsed.hostname if port in {None, default_port} else f"{parsed.hostname}:{port}"
    )
    return ResolvedSafeUrl(
        original_url=url,
        connect_url=urlunsplit(
            (parsed.scheme, connect_netloc, parsed.path, parsed.query, parsed.fragment)
        ),
        hostname=parsed.hostname,
        host_header=host_header,
        sni_hostname=parsed.hostname if parsed.scheme == "https" else None,
    )


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
    resolve_safe_url(url, require_https=require_https)


__all__ = ["ResolvedSafeUrl", "UrlNotSafe", "resolve_safe_url", "validate_safe_url"]
