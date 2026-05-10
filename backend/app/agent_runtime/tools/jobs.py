"""Job search tool: search_jobs.

Migrated from the old tools.py — Lever API search + detail fetch.
"""

from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry
from app.core.config import settings


def _lever_sites() -> list[str]:
    return [s.strip() for s in settings.LEVER_SITES.split(",") if s.strip()]


def _safe_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _matches_keywords(title: str, summary: str, keywords: str) -> bool:
    if not keywords.strip():
        return True
    haystack = f"{title}\n{summary}".lower()
    return all(t.lower() in haystack for t in keywords.split() if t.strip())


class SearchJobsArgs(BaseModel):
    keywords: str = Field(..., min_length=1, max_length=120)
    city: str = Field(default="", max_length=80)
    limit: int = Field(default=10, ge=1, le=50)
    job_id: str = Field(default="", description="If set, fetch detail for this specific job instead of searching.")


async def _search_jobs_handler(args: SearchJobsArgs, _ctx: AgentToolContext) -> dict[str, Any]:
    target_sites = _lever_sites()

    # Detail mode
    if args.job_id:
        return await _fetch_detail(args.job_id, target_sites)

    # Search mode
    jobs: list[dict[str, Any]] = []
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for site in target_sites:
            url = f"{settings.LEVER_API_BASE}/postings/{site}?mode=json"
            resp = await client.get(url)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, list):
                continue
            for item in data:
                title = _safe_text(item.get("text"))
                desc = _safe_text(item.get("descriptionPlain"))
                loc = _safe_text((item.get("categories") or {}).get("location"))
                if args.city and args.city.lower() not in loc.lower():
                    continue
                if not _matches_keywords(title, desc, args.keywords):
                    continue
                jobs.append({
                    "site": site,
                    "job_id": _safe_text(item.get("id")),
                    "title": title, "location": loc,
                    "team": _safe_text((item.get("categories") or {}).get("team")),
                    "hosted_url": _safe_text(item.get("hostedUrl")),
                    "summary": desc[:280],
                })
                if len(jobs) >= args.limit:
                    break
            if len(jobs) >= args.limit:
                break
    return {"source": "lever", "count": len(jobs), "jobs": jobs[:args.limit]}


async def _fetch_detail(job_id: str, sites: list[str]) -> dict[str, Any]:
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for site in sites:
            url = f"{settings.LEVER_API_BASE}/postings/{site}/{job_id}?mode=json"
            resp = await client.get(url)
            if resp.status_code != 200:
                continue
            item = resp.json()
            return {
                "source": "lever", "site": site,
                "job_id": _safe_text(item.get("id", job_id)),
                "title": _safe_text(item.get("text")),
                "location": _safe_text((item.get("categories") or {}).get("location")),
                "team": _safe_text((item.get("categories") or {}).get("team")),
                "hosted_url": _safe_text(item.get("hostedUrl")),
                "apply_url": _safe_text(item.get("applyUrl")),
                "description_plain": _safe_text(item.get("descriptionPlain")),
                "additional_plain": _safe_text(item.get("additionalPlain")),
            }
    return {"error": "job not found", "job_id": job_id}


registry.register(ToolEntry(
    name="search_jobs",
    description="Search job postings from Lever. Use keywords to search. Set job_id to fetch a specific job's full description instead of searching.",
    args_model=SearchJobsArgs,
    handler=_search_jobs_handler,
    max_result_chars=12000,
    emoji="💼",
))
