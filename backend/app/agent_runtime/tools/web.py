"""Web tools: web_search (Tavily) and read_url (httpx + markdownify).

web_search — Internet search via Tavily API.
read_url   — Extract page content as Markdown via httpx.
"""

import logging
import os
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry

logger = logging.getLogger(__name__)


# ── web_search ───────────────────────────────────────────────────────────

class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=300, description="Search query")
    limit: int = Field(default=5, ge=1, le=10, description="Max results")


def _tavily_available() -> bool:
    return bool(os.getenv("TAVILY_API_KEY"))


async def _web_search_handler(args: WebSearchArgs, _ctx: AgentToolContext) -> dict[str, Any]:
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return {"error": "TAVILY_API_KEY not set"}

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

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(args.url, headers=headers)

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
