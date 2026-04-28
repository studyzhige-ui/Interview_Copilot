import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func

from llama_index.core.tools import FunctionTool

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.chat import ChatSession
from app.models.interview import AnalysisResult, Interview
from app.models.user import User


def _lever_sites() -> list[str]:
    return [site.strip() for site in settings.LEVER_SITES.split(",") if site.strip()]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _matches_keywords(title: str, summary: str, keywords: str) -> bool:
    if not keywords.strip():
        return True
    haystack = f"{title}\n{summary}".lower()
    return all(token.lower() in haystack for token in keywords.split() if token.strip())


def _is_valid_site(site: str) -> bool:
    return site in set(_lever_sites())


class EmptyArgs(BaseModel):
    pass


class SearchJobsArgs(BaseModel):
    keywords: str = Field(..., min_length=1, max_length=120)
    city: str = Field(default="", max_length=80)
    limit: int = Field(default=settings.LEVER_DEFAULT_LIMIT, ge=1, le=100)
    sites: list[str] | None = None


class FetchJobDetailArgs(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=100)
    site: str = Field(default="", max_length=80)


class SearchInterviewQAArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


@dataclass
class AgentToolContext:
    user_id: str
    session_id: str


@dataclass
class RuntimeTool:
    name: str
    description: str
    args_model: type[BaseModel]
    function_tool: FunctionTool
    handler: Callable[[BaseModel, AgentToolContext], Awaitable[dict[str, Any]]]

    def to_openai_tool(self) -> dict[str, Any]:
        payload = self.function_tool.metadata.to_openai_tool()
        if settings.AGENT_TOOL_SCHEMA_STRICT:
            payload["function"]["strict"] = True
        return payload

    def validate_args(self, args: dict[str, Any]) -> BaseModel:
        args_json = json.dumps(args, ensure_ascii=False)
        if len(args_json) > settings.AGENT_MAX_TOOL_ARG_CHARS:
            raise ValueError("tool args too large")
        return self.args_model.model_validate(args)

    async def execute(self, args: dict[str, Any], ctx: AgentToolContext) -> dict[str, Any]:
        validated = self.validate_args(args)
        return await self.handler(validated, ctx)


async def _search_jobs_handler(args: SearchJobsArgs, _: AgentToolContext) -> dict[str, Any]:
    requested_sites = [s.strip() for s in (args.sites or []) if s.strip()]
    if requested_sites:
        invalid = [site for site in requested_sites if not _is_valid_site(site)]
        if invalid:
            return {"error": "unauthorized site requested", "invalid_sites": invalid}
        target_sites = requested_sites
    else:
        target_sites = _lever_sites()

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
                description = _safe_text(item.get("descriptionPlain"))
                location = _safe_text((item.get("categories") or {}).get("location"))
                if args.city and args.city.lower() not in location.lower():
                    continue
                if not _matches_keywords(title, description, args.keywords):
                    continue
                jobs.append(
                    {
                        "site": site,
                        "job_id": _safe_text(item.get("id")),
                        "title": title,
                        "location": location,
                        "team": _safe_text((item.get("categories") or {}).get("team")),
                        "commitment": _safe_text((item.get("categories") or {}).get("commitment")),
                        "hosted_url": _safe_text(item.get("hostedUrl")),
                        "apply_url": _safe_text(item.get("applyUrl")),
                        "summary": description[:280],
                    }
                )
                if len(jobs) >= args.limit:
                    break
            if len(jobs) >= args.limit:
                break
    return {
        "source": "lever",
        "sites_scanned": target_sites,
        "count": len(jobs),
        "jobs": jobs[: args.limit],
    }


async def _fetch_job_detail_handler(args: FetchJobDetailArgs, _: AgentToolContext) -> dict[str, Any]:
    if args.site:
        if not _is_valid_site(args.site):
            return {"error": "unauthorized site requested", "invalid_site": args.site}
        sites_to_try = [args.site]
    else:
        sites_to_try = _lever_sites()

    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for target_site in sites_to_try:
            url = f"{settings.LEVER_API_BASE}/postings/{target_site}/{args.job_id}?mode=json"
            resp = await client.get(url)
            if resp.status_code != 200:
                continue
            item = resp.json()
            lists = item.get("lists")
            return {
                "source": "lever",
                "site": target_site,
                "job_id": _safe_text(item.get("id", args.job_id)),
                "title": _safe_text(item.get("text")),
                "location": _safe_text((item.get("categories") or {}).get("location")),
                "team": _safe_text((item.get("categories") or {}).get("team")),
                "hosted_url": _safe_text(item.get("hostedUrl")),
                "apply_url": _safe_text(item.get("applyUrl")),
                "description_plain": _safe_text(item.get("descriptionPlain")),
                "description_body_plain": _safe_text(item.get("descriptionBodyPlain")),
                "additional_plain": _safe_text(item.get("additionalPlain")),
                "lists": lists if isinstance(lists, list) else [],
            }
    return {"error": "job not found from configured sites", "job_id": args.job_id}


def _load_profile_sync(user_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == user_id).first()
        latest_session = (
            db.query(ChatSession)
            .filter(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .first()
        )
        interview_count = db.query(Interview).filter(Interview.user_id == user_id).count()
        avg_score = (
            db.query(func.avg(AnalysisResult.score))
            .join(Interview, Interview.id == AnalysisResult.interview_id)
            .filter(Interview.user_id == user_id)
            .scalar()
        )
        latest_analysis = (
            db.query(AnalysisResult)
            .join(Interview, Interview.id == AnalysisResult.interview_id)
            .filter(Interview.user_id == user_id)
            .order_by(AnalysisResult.id.desc())
            .first()
        )
        return {
            "username": user.username if user else user_id,
            "email": user.email if user else None,
            "is_active": bool(user.is_active) if user else True,
            "latest_chat_summary": latest_session.summary if latest_session else "",
            "interview_count": interview_count,
            "average_interview_score": round(float(avg_score), 2) if avg_score is not None else None,
            "latest_feedback": (latest_analysis.feedback[:800] if latest_analysis and latest_analysis.feedback else ""),
        }
    finally:
        db.close()


async def _get_user_profile_handler(_: EmptyArgs, ctx: AgentToolContext) -> dict[str, Any]:
    profile = await asyncio.to_thread(_load_profile_sync, ctx.user_id)
    return {"profile": profile}


async def _search_interview_qa_handler(args: SearchInterviewQAArgs, ctx: AgentToolContext) -> dict[str, Any]:
    from app.rag.retriever import query_knowledge_base

    result = await query_knowledge_base(
        query_str=args.query,
        user_id=ctx.user_id,
        source_type="interview_qa",
    )
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
    }


async def _schema_stub(**_: Any) -> dict[str, Any]:
    return {}


def _build_runtime_tool(
    *,
    name: str,
    description: str,
    args_model: type[BaseModel],
    handler: Callable[[BaseModel, AgentToolContext], Awaitable[dict[str, Any]]],
) -> RuntimeTool:
    function_tool = FunctionTool.from_defaults(
        name=name,
        description=description,
        async_fn=_schema_stub,
        fn_schema=args_model,
    )
    return RuntimeTool(
        name=name,
        description=description,
        args_model=args_model,
        function_tool=function_tool,
        handler=handler,
    )


def build_default_tool_registry() -> dict[str, RuntimeTool]:
    tools = [
        _build_runtime_tool(
            name="search_jobs",
            description="Search job postings from configured Lever sites.",
            args_model=SearchJobsArgs,
            handler=_search_jobs_handler,
        ),
        _build_runtime_tool(
            name="fetch_job_detail",
            description="Fetch full job description by job_id and optional site from Lever.",
            args_model=FetchJobDetailArgs,
            handler=_fetch_job_detail_handler,
        ),
        _build_runtime_tool(
            name="get_user_profile",
            description="Load current user's profile, latest chat summary, and interview stats.",
            args_model=EmptyArgs,
            handler=_get_user_profile_handler,
        ),
        _build_runtime_tool(
            name="search_interview_qa",
            description="Search interview QA knowledge base for preparation hints and topic coverage.",
            args_model=SearchInterviewQAArgs,
            handler=_search_interview_qa_handler,
        ),
    ]
    return {tool.name: tool for tool in tools}


def build_openai_tool_schemas(registry: dict[str, RuntimeTool]) -> list[dict[str, Any]]:
    return [tool.to_openai_tool() for tool in registry.values()]


def format_tool_manifest(registry: dict[str, RuntimeTool]) -> str:
    manifest: list[dict[str, Any]] = []
    for tool in registry.values():
        tool_schema = tool.to_openai_tool()
        manifest.append(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool_schema["function"]["parameters"],
                "strict": tool_schema["function"].get("strict", False),
            }
        )
    return json.dumps(manifest, ensure_ascii=False, indent=2)


def parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    if not raw_arguments:
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except Exception as exc:
        raise ValueError(f"tool arguments are not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    return parsed


def safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"non_serializable": str(value)}, ensure_ascii=False)


def format_validation_error(exc: ValidationError) -> dict[str, Any]:
    return {"error": "tool args validation failed", "details": exc.errors()}
