"""Job search tool: search_jobs.

Wraps Lever API for job search and detail retrieval.
"""

import logging
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry
from app.core.config import settings

logger = logging.getLogger(__name__)


def _lever_sites() -> list[str]:
    return [s.strip() for s in settings.LEVER_SITES.split(",") if s.strip()]


def _jobs_available() -> bool:
    """Manifest gate: hide search_jobs when no Lever sites are configured."""
    return bool(_lever_sites())


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
    job_id: str = Field(
        default="",
        description="If set, fetch detail for this specific job instead of searching.",
    )


async def _search_jobs_handler(
    args: SearchJobsArgs,
    _ctx: AgentToolContext,
) -> dict[str, Any]:
    target_sites = _lever_sites()
    if not target_sites:
        return {"error": "No Lever sites configured", "count": 0}

    if args.job_id:
        return await _fetch_detail(args.job_id, target_sites)

    jobs: list[dict[str, Any]] = []
    timeout = httpx.Timeout(20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for site in target_sites:
                url = f"{settings.LEVER_API_BASE}/postings/{site}?mode=json"
                try:
                    resp = await client.get(url)
                except httpx.TimeoutException:
                    logger.warning("Lever API timeout for site=%s", site)
                    continue
                if resp.status_code != 200:
                    continue
                try:
                    data = resp.json()
                except Exception:
                    continue
                if not isinstance(data, list):
                    continue
                for item in data:
                    title = _safe_text(item.get("text"))
                    desc = _safe_text(item.get("descriptionPlain"))
                    loc = _safe_text(
                        (item.get("categories") or {}).get("location"),
                    )
                    if args.city and args.city.lower() not in loc.lower():
                        continue
                    if not _matches_keywords(title, desc, args.keywords):
                        continue
                    jobs.append(
                        {
                            "site": site,
                            "job_id": _safe_text(item.get("id")),
                            "title": title,
                            "location": loc,
                            "team": _safe_text(
                                (item.get("categories") or {}).get("team"),
                            ),
                            "hosted_url": _safe_text(item.get("hostedUrl")),
                            "summary": desc[:280],
                        }
                    )
                    if len(jobs) >= args.limit:
                        break
                if len(jobs) >= args.limit:
                    break
    except httpx.TimeoutException:
        return {
            "error": "Lever API request timed out",
            "count": len(jobs),
            "jobs": jobs,
        }
    except Exception as exc:
        logger.warning("search_jobs failed: %s", exc)
        return {
            "error": f"Lever API request failed: {exc}",
            "count": len(jobs),
            "jobs": jobs,
        }

    return {"source": "lever", "count": len(jobs), "jobs": jobs[: args.limit]}


async def _fetch_detail(job_id: str, sites: list[str]) -> dict[str, Any]:
    timeout = httpx.Timeout(20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for site in sites:
                url = f"{settings.LEVER_API_BASE}/postings/{site}/{job_id}?mode=json"
                try:
                    resp = await client.get(url)
                except httpx.TimeoutException:
                    continue
                if resp.status_code != 200:
                    continue
                try:
                    item = resp.json()
                except Exception:
                    continue
                return {
                    "source": "lever",
                    "site": site,
                    "job_id": _safe_text(item.get("id", job_id)),
                    "title": _safe_text(item.get("text")),
                    "location": _safe_text(
                        (item.get("categories") or {}).get("location"),
                    ),
                    "team": _safe_text(
                        (item.get("categories") or {}).get("team"),
                    ),
                    "hosted_url": _safe_text(item.get("hostedUrl")),
                    "apply_url": _safe_text(item.get("applyUrl")),
                    "description_plain": _safe_text(
                        item.get("descriptionPlain"),
                    ),
                    "additional_plain": _safe_text(
                        item.get("additionalPlain"),
                    ),
                }
    except httpx.TimeoutException:
        return {"error": "Lever API request timed out", "job_id": job_id}
    except Exception as exc:
        logger.warning("search_jobs detail fetch failed: %s", exc)
        return {"error": f"Lever API request failed: {exc}", "job_id": job_id}

    return {"error": "job not found", "job_id": job_id}


registry.register(
    ToolEntry(
        name="search_jobs",
        description=(
            "Search job postings from configured Lever company pages. "
            "Use keywords to find positions; optionally filter by city. "
            "Set job_id to fetch a specific posting's full description."
        ),
        args_model=SearchJobsArgs,
        handler=_search_jobs_handler,
        check_fn=_jobs_available,
        max_result_chars=12_000,
        emoji="💼",
    )
)
