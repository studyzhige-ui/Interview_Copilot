"""Web tools: web_search (Tavily) and read_url (httpx + markdownify).

web_search — Internet search via Tavily API.
read_url   — Extract page content as Markdown via httpx, with SSRF
             guard that resolves the host's DNS up-front and refuses
             anything pointing at private / loopback / link-local /
             reserved / multicast space.
"""

import asyncio
import logging
import os
from typing import Any
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry
from app.core.ssrf import UrlNotSafe as _UrlNotSafe
from app.core.ssrf import validate_safe_url as _validate_safe_url

logger = logging.getLogger(__name__)


# SSRF guard hoisted to ``app.core.ssrf`` (P6-M) so the model-provider
# settings endpoint can reuse the same checks on ``api_base_override``.
# Aliased above as ``_UrlNotSafe`` / ``_validate_safe_url`` so the rest
# of this file (and any tests that patched the private names) keeps
# working without rename churn.


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
            from app.services.auth.user_api_key_service import get_user_api_key_plaintext
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
