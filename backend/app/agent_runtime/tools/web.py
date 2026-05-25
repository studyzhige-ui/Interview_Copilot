"""Web tools: web_search (Tavily) and read_url (httpx + markdownify).

web_search — Internet search via Tavily API.
read_url   — Extract page content as Markdown via httpx, with SSRF
             guard that resolves the host's DNS up-front and refuses
             anything pointing at private / loopback / link-local /
             reserved / multicast space.
"""

import asyncio
import ipaddress
import logging
import os
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry

logger = logging.getLogger(__name__)


# ── SSRF guard ───────────────────────────────────────────────────────────
#
# Why this exists: the agent is reachable via prompt injection (a
# user can paste a JD that says "for QA, fetch
# http://169.254.169.254/..."), and the LLM will obediently call
# ``read_url`` on whatever it's told. Without a guard the tool would
# happily hit the AWS instance-metadata endpoint and surface IAM
# credentials, or scan the internal network for unauthenticated
# services. Both have happened to real shipped LLM agents.
#
# What it covers:
#   • non-http(s) schemes (rules out file://, gopher://, dict:// …)
#   • RFC1918 (10/8, 172.16/12, 192.168/16) via ``is_private``
#   • Loopback (127.0.0.0/8 + ::1) via ``is_loopback``
#   • Link-local (169.254/16 — AWS/GCP/Azure metadata) via ``is_link_local``
#   • Reserved / multicast / unspecified (broad belt-and-braces)
#
# What it does NOT cover: DNS rebinding. A determined attacker could
# serve a public IP at first lookup and a private one at httpx's
# subsequent connect-time lookup. Mitigating requires resolve-once
# then dial-via-resolved-IP, which is a bigger refactor — left as a
# follow-up if the threat model warrants. The current guard blocks
# 99% of the prompt-injection-driven SSRF attempts that don't have
# attacker-controlled DNS.


class _UrlNotSafe(ValueError):
    """Raised when an SSRF-prone URL is detected; mapped to a tool
    error response so the agent sees a clear refusal without
    crashing the run."""


def _validate_safe_url(url: str) -> None:
    """Block the URL if its scheme is not http(s) or if any resolved
    IP lands in private / loopback / link-local / reserved /
    multicast / unspecified space.

    Synchronous: ``socket.getaddrinfo`` is blocking. The caller
    offloads via ``asyncio.to_thread`` so the event loop stays
    responsive on a slow DNS server.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise _UrlNotSafe(f"scheme not allowed: {parsed.scheme!r}")
    if not parsed.hostname:
        raise _UrlNotSafe("missing hostname")

    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        # DNS failure is itself a refuse signal — without a resolved
        # IP we can't make a safety decision.
        raise _UrlNotSafe(f"dns resolution failed: {exc}") from exc

    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise _UrlNotSafe(f"bad ip from dns: {ip_str!r}") from exc
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise _UrlNotSafe(
                f"refusing url whose host resolves to {ip} "
                f"(private/loopback/reserved space)"
            )


_MAX_REDIRECTS = 5


# ── web_search ───────────────────────────────────────────────────────────

class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=300, description="Search query")
    limit: int = Field(default=5, ge=1, le=10, description="Max results")


def _tavily_available() -> bool:
    # Manifest gate — runs without a user context (registry's
    # ``available()`` predicate is queried once at startup for global
    # OpenAI-schema generation). True if EITHER per-user keys can
    # exist (we always allow that — the actual check is per-request)
    # OR the global env-var fallback is set. In practice this stays
    # ``True`` whenever the env var is configured, and we let the
    # per-request handler return a clear error when neither source
    # has a key for the actual calling user.
    return bool(os.getenv("TAVILY_API_KEY"))


def _resolve_tavily_key(user_id: str | None) -> str:
    """Prefer per-user encrypted key, fall back to global env var.

    The same resolution shape as ``model_registry.resolve_api_key``
    but specialised for Tavily (not a chat-LLM ``ModelProfile``).
    Pre-fix the web_search tool only read the env var so a
    multi-tenant deploy had every user share one Tavily account
    (billing + quota cross-tenant).
    """
    if user_id:
        try:
            from app.services.user_api_key_service import get_user_api_key_plaintext
            per_user = get_user_api_key_plaintext(user_id, "tavily")
            if per_user:
                return per_user
        except Exception as exc:  # noqa: BLE001
            logger.warning("tavily per-user key lookup failed: %s", exc)
    return os.getenv("TAVILY_API_KEY", "")


async def _web_search_handler(args: WebSearchArgs, ctx: AgentToolContext) -> dict[str, Any]:
    api_key = _resolve_tavily_key(ctx.user_id)
    if not api_key:
        return {"error": "TAVILY_API_KEY not set (and no per-user key configured)"}

    timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": args.query,
                "max_results": args.limit,
                "include_raw_content": False,
                "include_images": False,
            },
        )
        if resp.status_code != 200:
            return {"error": f"Tavily API error: {resp.status_code}", "detail": resp.text[:500]}

        data = resp.json()
        results = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("content", "")[:300],
            })
        return {
            "source": "tavily",
            "query": args.query,
            "count": len(results),
            "results": results,
        }


# ── read_url ─────────────────────────────────────────────────────────────

class ReadUrlArgs(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000, description="URL to extract content from")


async def _read_url_handler(args: ReadUrlArgs, _ctx: AgentToolContext) -> dict[str, Any]:
    timeout = httpx.Timeout(20.0)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; InterviewCopilot/1.0)",
        "Accept": "text/html,application/xhtml+xml,text/plain",
    }

    # SSRF guard — refuse before we even open the TCP socket. We
    # also revalidate each hop manually below because
    # ``follow_redirects=True`` would let an attacker hop from a
    # public domain to a private one via a 302 Location header.
    try:
        await asyncio.to_thread(_validate_safe_url, args.url)
    except _UrlNotSafe as exc:
        logger.warning("read_url refused unsafe url=%r: %s", args.url, exc)
        return {"error": f"refused by safety check: {exc}", "url": args.url}

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            current_url = args.url
            resp = None
            for _ in range(_MAX_REDIRECTS + 1):
                resp = await client.get(current_url, headers=headers)
                if resp.status_code not in (301, 302, 303, 307, 308):
                    break
                location = resp.headers.get("location", "")
                if not location:
                    break
                next_url = urljoin(str(resp.url), location)
                try:
                    await asyncio.to_thread(_validate_safe_url, next_url)
                except _UrlNotSafe as exc:
                    logger.warning(
                        "read_url refused redirect target=%r: %s", next_url, exc
                    )
                    return {
                        "error": f"refused redirect to unsafe url: {exc}",
                        "url": args.url,
                    }
                current_url = next_url
            else:
                return {"error": "too many redirects", "url": args.url}

        assert resp is not None
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "url": args.url}

        content_type = resp.headers.get("content-type", "")
        raw_text = resp.text

        # Convert HTML to readable text
        if "html" in content_type:
            try:
                from markdownify import markdownify as md
                text = md(raw_text, strip=["img", "script", "style"])
            except ImportError:
                # Fallback: strip HTML tags with regex
                import re
                text = re.sub(r"<[^>]+>", "", raw_text)
                text = re.sub(r"\s+", " ", text).strip()
        else:
            text = raw_text

        # Truncate large pages
        max_chars = 15000
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]

        return {
            "url": str(resp.url),
            "title": _extract_title(raw_text) if "html" in content_type else "",
            "content": text.strip(),
            "char_count": len(text),
            "truncated": truncated,
        }

    except httpx.TimeoutException:
        return {"error": "Request timed out", "url": args.url}
    except Exception as exc:
        return {"error": f"Failed to fetch URL: {exc}", "url": args.url}


def _extract_title(html: str) -> str:
    import re
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip()[:200] if match else ""


# ── Registration ─────────────────────────────────────────────────────────

registry.register(ToolEntry(
    name="web_search",
    description="Search the internet for information. Returns titles, URLs, and descriptions. Use for company info, interview experiences, technical articles, salary data, etc.",
    args_model=WebSearchArgs,
    handler=_web_search_handler,
    check_fn=_tavily_available,
    max_result_chars=12000,
    emoji="🔍",
))

registry.register(ToolEntry(
    name="read_url",
    description="Extract text content from a web page URL. Returns the page content as readable text. Use after web_search to read specific pages in detail.",
    args_model=ReadUrlArgs,
    handler=_read_url_handler,
    max_result_chars=16000,
    emoji="📄",
))
