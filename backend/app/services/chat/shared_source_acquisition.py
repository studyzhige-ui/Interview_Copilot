"""Shared, owner-routed read-only source acquisition for one Turn.

The adapter converts a closed set of typed read requests into the existing
``RetrievalResult``/grounding contract. It owns no facts and persists no
generic source rows, Source Registry, universal CareerState aggregate, or
universal context DTO. History, Gmail Observation, Artifact, and every named
career-domain object remain authoritative in their existing services/tables;
this adapter reads those owners directly. Explicit public URLs use the exact
SSRF-safe reader exposed by the Agent's concrete ``read_url`` integration, so
Chat and Agent cannot drift into different network boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable

from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity
from app.models.offer import Offer
from app.rag.domain.models import (
    EMPTY_NO_CANDIDATES,
    RetrievalResult,
    RetrievalState,
    SearchIntent,
)
from app.schemas.history_search import HistorySearchQuery
from app.schemas.job_opportunity import JobOpportunityView, NextActionView
from app.schemas.offer import OfferView
from app.services import (
    ability_signal_service,
    artifact_service,
    career_profile_service,
    gmail_observation_service,
    offer_service,
)
from app.services.career_process_service import (
    list_job_opportunities,
    list_next_actions,
)
from app.services.interaction_history_service import (
    get_interaction_history_record,
    search_interaction_history,
)

from .source_requests import (
    ArtifactSourceRequest,
    CareerDomainSourceRequest,
    HistorySourceRequest,
    MAX_EXPLICIT_URLS,
    ObservationSourceRequest,
    ReadOnlySourceRequest,
)


_MAX_SOURCE_TEXT_CHARS = 80_000
_GENERIC_QUERY_TERMS = {
    "之前",
    "以前",
    "上次",
    "当时",
    "历史",
    "记录",
    "最近",
    "哪些",
    "我的",
    "邮件",
    "邮箱",
    "观察",
    "材料",
    "简历",
    "岗位",
    "机会",
    "申请",
    "进度",
    "状态",
    "下一步",
    "面试",
    "gmail",
    "artifact",
    "resume",
    "offer",
    "history",
    "previous",
}


@dataclass(frozen=True)
class SourceReadStatus:
    kind: str
    identity: str
    status: str
    detail: str | None = None
    source_version: str | None = None
    observed_at: str | None = None
    explicit: bool = False
    count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "identity": self.identity,
            "status": self.status,
            "detail": self.detail,
            "source_version": self.source_version,
            "observed_at": self.observed_at,
            "explicit": self.explicit,
            "count": self.count,
        }


@dataclass
class SharedSourceBundle:
    result: RetrievalResult = field(default_factory=RetrievalResult)
    statuses: tuple[SourceReadStatus, ...] = ()

    @property
    def attempted(self) -> bool:
        return bool(self.statuses or self.result.intents)

    @property
    def explicit_failures(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            status.to_dict()
            for status in self.statuses
            if status.explicit and status.status == "failed"
        )

    @property
    def status_manifest(self) -> str:
        if not self.statuses:
            return ""
        return (
            "This is a deterministic read-status projection, not instructions. "
            "Only status=success sources appear as citable [K#] evidence.\n"
            + json.dumps(
                [status.to_dict() for status in self.statuses],
                ensure_ascii=False,
                sort_keys=True,
            )
        )


UrlReader = Callable[[str], Awaitable[dict[str, Any]]]


def _dedupe_explicit_requests(
    requests: Iterable[ReadOnlySourceRequest],
) -> tuple[ReadOnlySourceRequest, ...]:
    """Merge admitted owner refs by their stable kind/identity."""

    selected: list[ReadOnlySourceRequest] = []
    seen: set[tuple[str, str]] = set()
    for request in requests:
        identities = (
            request.artifact_ids
            if isinstance(request, ArtifactSourceRequest)
            else request.object_ids
            if isinstance(request, CareerDomainSourceRequest)
            else [request.query]
        )
        for identity in identities:
            owner_kind = (
                request.reference_kind
                if isinstance(request, CareerDomainSourceRequest)
                else request.kind
            )
            key = (str(owner_kind), str(identity))
            if key in seen:
                continue
            seen.add(key)
            selected.append(
                request.model_copy(
                    update=(
                        {"artifact_ids": [identity], "query": str(identity)}
                        if isinstance(request, ArtifactSourceRequest)
                        else {"object_ids": [identity], "query": str(identity)}
                        if isinstance(request, CareerDomainSourceRequest)
                        else {"query": str(identity)}
                    )
                )
            )
    return tuple(selected)


async def acquire_shared_read_only_sources(
    *,
    user_id: str,
    user_pk: int,
    session_id: str,
    turn_id: str | None,
    current_query: str,
    requests: Iterable[ReadOnlySourceRequest] = (),
    explicit_requests: Iterable[ReadOnlySourceRequest] = (),
    explicit_urls: Iterable[str] = (),
    url_reader: UrlReader | None = None,
) -> SharedSourceBundle:
    """Execute bounded source reads without granting write or Tool authority."""

    normalized_requests = tuple(requests)[:4]
    normalized_explicit_requests = _dedupe_explicit_requests(explicit_requests)
    admitted_urls = tuple(dict.fromkeys(str(url) for url in explicit_urls))
    normalized_urls = admitted_urls[:MAX_EXPLICIT_URLS]
    overflow_count = max(0, len(admitted_urls) - len(normalized_urls))
    if (
        not normalized_requests
        and not normalized_explicit_requests
        and not normalized_urls
        and not overflow_count
    ):
        return SharedSourceBundle()

    reader = url_reader or (
        lambda url: _read_url_through_agent_integration(
            url,
            user_id=user_id,
            user_pk=user_pk,
            session_id=session_id,
            turn_id=turn_id,
        )
    )
    url_tasks = [
        asyncio.create_task(_read_explicit_url(url, index=index, reader=reader))
        for index, url in enumerate(normalized_urls)
    ]
    owner_task = (
        asyncio.create_task(
            asyncio.to_thread(
                _read_owned_sources,
                normalized_requests,
                user_pk=user_pk,
                session_id=session_id,
                current_query=current_query,
                explicit=False,
            )
        )
        if normalized_requests
        else None
    )
    explicit_owner_task = (
        asyncio.create_task(
            asyncio.to_thread(
                _read_owned_sources,
                normalized_explicit_requests,
                user_pk=user_pk,
                session_id=session_id,
                current_query=current_query,
                explicit=True,
            )
        )
        if normalized_explicit_requests
        else None
    )

    url_parts: list[SharedSourceBundle] = []
    if url_tasks:
        url_outcomes = await asyncio.gather(*url_tasks, return_exceptions=True)
        for url, outcome in zip(normalized_urls, url_outcomes, strict=True):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            if isinstance(outcome, Exception):
                url_parts.append(
                    SharedSourceBundle(
                        statuses=(
                            SourceReadStatus(
                                kind="url",
                                identity=url,
                                status="failed",
                                detail=(
                                    f"{type(outcome).__name__}: URL source "
                                    "boundary failed"
                                ),
                                observed_at=utc_now().isoformat(),
                                explicit=True,
                            ),
                        )
                    )
                )
            else:
                url_parts.append(outcome)
    if owner_task:
        try:
            owner_part = await owner_task
        except Exception as exc:  # noqa: BLE001 - source boundary stays typed
            owner_part = _owner_boundary_failure(
                normalized_requests,
                explicit=False,
                error=exc,
            )
    else:
        owner_part = SharedSourceBundle()
    if explicit_owner_task:
        try:
            explicit_owner_part = await explicit_owner_task
        except Exception as exc:  # noqa: BLE001 - explicit input must not vanish
            explicit_owner_part = _owner_boundary_failure(
                normalized_explicit_requests,
                explicit=True,
                error=exc,
            )
    else:
        explicit_owner_part = SharedSourceBundle()
    overflow_part = (
        SharedSourceBundle(
            statuses=(
                SourceReadStatus(
                    kind="url",
                    identity="explicit_url_overflow",
                    status="failed",
                    detail=(
                        f"Explicit URL limit is {MAX_EXPLICIT_URLS}; "
                        f"{overflow_count} additional "
                        "URL(s) were not read"
                    ),
                    explicit=True,
                    count=overflow_count,
                ),
            )
        )
        if overflow_count
        else SharedSourceBundle()
    )
    bundles = [*url_parts, owner_part, explicit_owner_part, overflow_part]
    chunks: list[dict[str, Any]] = []
    intents: list[SearchIntent] = []
    statuses: list[SourceReadStatus] = []
    seen_nodes: set[str] = set()
    for bundle in bundles:
        intents.extend(bundle.result.intents)
        statuses.extend(bundle.statuses)
        for chunk in bundle.result.chunks:
            identity = str(chunk.get("node_id") or chunk.get("chunk_id") or "")
            if identity and identity in seen_nodes:
                continue
            if identity:
                seen_nodes.add(identity)
            chunks.append(chunk)
    return SharedSourceBundle(
        result=RetrievalResult(
            chunks=chunks,
            state=RetrievalState(
                retrieval_hit=bool(chunks),
                empty_reason=None if chunks else EMPTY_NO_CANDIDATES,
            ),
            diagnostics={
                "shared_source_request_count": len(normalized_requests),
                "explicit_owner_request_count": len(normalized_explicit_requests),
                "explicit_url_count": len(admitted_urls),
                "explicit_url_overflow_count": overflow_count,
                "successful_source_count": sum(
                    status.status == "success" for status in statuses
                ),
                "failed_source_count": sum(
                    status.status == "failed" for status in statuses
                ),
            },
            intents=intents,
        ),
        statuses=tuple(statuses),
    )


async def _read_url_through_agent_integration(
    url: str,
    *,
    user_id: str,
    user_pk: int,
    session_id: str,
    turn_id: str | None,
) -> dict[str, Any]:
    # Import lazily so a Chat-only process pays no Agent Tool registration cost
    # unless it actually receives an explicit URL.  Calling the concrete
    # handler directly deliberately creates SourceResult evidence, not a fake
    # Tool Call or Tool receipt.
    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.web import ReadUrlArgs, _read_url_handler

    return await _read_url_handler(
        ReadUrlArgs(url=url),
        AgentToolContext(
            user_id=user_id,
            user_pk=user_pk,
            session_id=session_id,
            turn_id=turn_id,
        ),
    )


async def _read_explicit_url(
    url: str,
    *,
    index: int,
    reader: UrlReader,
) -> SharedSourceBundle:
    intent = SearchIntent(
        intent_id=f"shared:url:{index}",
        query=url,
        keywords=[url],
    )
    observed_at = utc_now()
    try:
        payload = await reader(url)
    except Exception as exc:  # noqa: BLE001 - boundary reports typed failure
        return SharedSourceBundle(
            result=_empty_result(intent),
            statuses=(
                SourceReadStatus(
                    kind="url",
                    identity=url,
                    status="failed",
                    detail=f"{type(exc).__name__}: URL read failed",
                    observed_at=observed_at.isoformat(),
                    explicit=True,
                ),
            ),
        )
    if payload.get("error"):
        return SharedSourceBundle(
            result=_empty_result(intent),
            statuses=(
                SourceReadStatus(
                    kind="url",
                    identity=url,
                    status="failed",
                    detail=str(payload.get("error"))[:500],
                    observed_at=observed_at.isoformat(),
                    explicit=True,
                ),
            ),
        )
    content = str(payload.get("content") or "").strip()
    if not content:
        return SharedSourceBundle(
            result=_empty_result(intent),
            statuses=(
                SourceReadStatus(
                    kind="url",
                    identity=url,
                    status="failed",
                    detail="URL returned no readable text",
                    observed_at=observed_at.isoformat(),
                    explicit=True,
                ),
            ),
        )
    resolved_url = str(payload.get("url") or url)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    version = f"sha256:{digest}"
    title = str(payload.get("title") or "").strip() or resolved_url
    chunk = _source_chunk(
        intent=intent,
        identity=f"web_url:{digest}",
        title=title,
        text=content,
        source_kind="web_url",
        source_version=version,
        observed_at=observed_at,
        score_source="explicit_url",
        extra={
            "source_url": resolved_url,
            "original_url": url,
            "content_sha256": digest,
            "projection_truncated": bool(payload.get("truncated")),
        },
    )
    return SharedSourceBundle(
        result=RetrievalResult(
            chunks=[chunk],
            state=RetrievalState(retrieval_hit=True),
            intents=[intent],
        ),
        statuses=(
            SourceReadStatus(
                kind="url",
                identity=resolved_url,
                status="success",
                source_version=version,
                observed_at=observed_at.isoformat(),
                explicit=True,
                count=1,
            ),
        ),
    )


def _read_owned_sources(
    requests: tuple[ReadOnlySourceRequest, ...],
    *,
    user_pk: int,
    session_id: str,
    current_query: str,
    explicit: bool,
) -> SharedSourceBundle:
    intents: list[SearchIntent] = []
    chunks: list[dict[str, Any]] = []
    statuses: list[SourceReadStatus] = []
    if user_pk <= 0:
        for index, request in enumerate(requests):
            intent = _request_intent(request, index)
            intents.append(intent)
            statuses.append(
                SourceReadStatus(
                    kind=request.kind,
                    identity=request.query,
                    status="failed",
                    detail="user_scope_unavailable",
                    explicit=explicit,
                )
            )
        return SharedSourceBundle(
            result=RetrievalResult(
                state=RetrievalState(empty_reason=EMPTY_NO_CANDIDATES),
                intents=intents,
            ),
            statuses=tuple(statuses),
        )

    db = SessionLocal()
    try:
        for index, request in enumerate(requests):
            intent = _request_intent(request, index)
            intents.append(intent)
            try:
                if isinstance(request, HistorySourceRequest):
                    selected = _read_history(
                        db,
                        request=request,
                        intent=intent,
                        user_pk=user_pk,
                        session_id=session_id,
                    )
                elif isinstance(request, ObservationSourceRequest):
                    selected = _read_observations(
                        db,
                        request=request,
                        intent=intent,
                        user_pk=user_pk,
                    )
                elif isinstance(request, ArtifactSourceRequest):
                    selected = _read_artifacts(
                        db,
                        request=request,
                        intent=intent,
                        user_pk=user_pk,
                    )
                elif isinstance(request, CareerDomainSourceRequest):
                    selected = _read_career_domains(
                        db,
                        request=request,
                        intent=intent,
                        user_pk=user_pk,
                    )
                else:  # pragma: no cover - closed discriminated union
                    raise TypeError(f"Unsupported source request: {type(request)!r}")
                chunks.extend(selected)
                statuses.append(
                    SourceReadStatus(
                        kind=request.kind,
                        identity=request.query or current_query,
                        status=(
                            "success" if selected else "failed" if explicit else "empty"
                        ),
                        detail=(
                            None
                            if selected or not explicit
                            else "explicit_owner_source_not_found_or_inaccessible"
                        ),
                        explicit=explicit,
                        count=len(selected),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - fail one source, keep others
                statuses.append(
                    SourceReadStatus(
                        kind=request.kind,
                        identity=request.query or current_query,
                        status="failed",
                        detail=f"{type(exc).__name__}: source read failed",
                        explicit=explicit,
                    )
                )
    finally:
        db.close()
    return SharedSourceBundle(
        result=RetrievalResult(
            chunks=chunks,
            state=RetrievalState(
                retrieval_hit=bool(chunks),
                empty_reason=None if chunks else EMPTY_NO_CANDIDATES,
            ),
            intents=intents,
        ),
        statuses=tuple(statuses),
    )


def _owner_boundary_failure(
    requests: tuple[ReadOnlySourceRequest, ...],
    *,
    explicit: bool,
    error: Exception,
) -> SharedSourceBundle:
    intents = [
        _request_intent(request, index) for index, request in enumerate(requests)
    ]
    return SharedSourceBundle(
        result=RetrievalResult(
            state=RetrievalState(empty_reason=EMPTY_NO_CANDIDATES),
            intents=intents,
        ),
        statuses=tuple(
            SourceReadStatus(
                kind=request.kind,
                identity=request.query,
                status="failed",
                detail=f"{type(error).__name__}: source boundary failed",
                explicit=explicit,
            )
            for request in requests
        ),
    )


def _request_intent(request: ReadOnlySourceRequest, index: int) -> SearchIntent:
    return SearchIntent(
        intent_id=f"shared:{request.kind}:{index}",
        query=request.query,
        keywords=_query_terms(request.query),
    )


def _read_history(
    db,
    *,
    request: HistorySourceRequest,
    intent: SearchIntent,
    user_pk: int,
    session_id: str,
) -> list[dict[str, Any]]:
    response = search_interaction_history(
        db,
        user_pk=user_pk,
        request=HistorySearchQuery(
            query=request.query,
            conversation_id=(
                session_id if request.scope == "current_conversation" else None
            ),
            limit=request.limit,
        ),
    )
    chunks: list[dict[str, Any]] = []
    for result in response.results:
        detail = get_interaction_history_record(
            db,
            user_pk=user_pk,
            identity=result.identity,
        )
        text = json.dumps(
            detail.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        chunks.append(
            _source_chunk(
                intent=intent,
                identity=result.identity,
                title=result.conversation_title or "Interaction History",
                text=text,
                source_kind="interaction_record",
                source_version=(
                    f"seq:{result.seq}"
                    if result.seq is not None
                    else f"tool_call:{result.tool_call_id}"
                ),
                observed_at=result.occurred_at,
                score_source="history_search",
                extra={"conversation_id": result.conversation_id},
            )
        )
    return chunks


def _read_observations(
    db,
    *,
    request: ObservationSourceRequest,
    intent: SearchIntent,
    user_pk: int,
) -> list[dict[str, Any]]:
    rows = gmail_observation_service.list_observations(
        db,
        user_pk=user_pk,
        statuses=set(request.statuses) if request.statuses else None,
        limit=50,
    )
    selected = _select_relevant(
        rows,
        query=request.query,
        limit=request.limit,
        renderer=lambda item: json.dumps(item, ensure_ascii=False, default=str),
    )
    chunks: list[dict[str, Any]] = []
    for row in selected:
        snapshot = dict(row.get("latest_snapshot") or {})
        identity = str(row.get("id") or "")
        snapshot_id = str(snapshot.get("id") or identity)
        chunks.append(
            _source_chunk(
                intent=intent,
                identity=f"gmail_observation:{identity}:{snapshot_id}",
                title=str(snapshot.get("subject") or "Gmail Observation"),
                text=json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
                source_kind="gmail_observation",
                source_version=str(
                    snapshot.get("snapshot_version") or row.get("version")
                ),
                observed_at=_datetime(
                    snapshot.get("observed_at") or row.get("observed_at")
                ),
                score_source="owner_read",
                extra={
                    "source_identity": f"gmail_observation:{identity}",
                    "provider": "gmail",
                },
            )
        )
    return chunks


def _read_artifacts(
    db,
    *,
    request: ArtifactSourceRequest,
    intent: SearchIntent,
    user_pk: int,
) -> list[dict[str, Any]]:
    rows = artifact_service.list_artifacts(
        db,
        user_pk=user_pk,
        include_archived=request.include_archived,
        limit=1000 if request.artifact_ids else 100,
    )
    allowed_ids = set(request.artifact_ids)
    if allowed_ids:
        rows = [row for row in rows if str(row[0].id) in allowed_ids]
    allowed_kinds = {value.casefold() for value in request.artifact_kinds}
    if allowed_kinds:
        rows = [row for row in rows if row[0].kind.casefold() in allowed_kinds]
    selected = _select_relevant(
        rows,
        query=request.query,
        limit=request.limit,
        renderer=lambda item: "\n".join(
            (
                str(item[0].kind),
                str(item[1].title),
                str(item[1].content_text or ""),
            )
        ),
    )
    chunks: list[dict[str, Any]] = []
    for artifact, version in selected:
        payload = {
            "artifact_id": artifact.id,
            "kind": artifact.kind,
            "archived_at": artifact.archived_at,
            "version": {
                "id": version.id,
                "version_no": version.version_no,
                "title": version.title,
                "content_text": version.content_text,
                "content_format": version.content_format,
                "file_asset_id": version.file_asset_id,
                "file_asset_version": version.file_asset_version,
                "origin_kind": version.origin_kind,
                "created_at": version.created_at,
            },
        }
        chunks.append(
            _source_chunk(
                intent=intent,
                identity=f"artifact_version:{version.id}",
                title=version.title,
                text=json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, default=str
                ),
                source_kind="artifact_version",
                source_version=(
                    version.file_asset_version
                    or f"artifact-version:{version.version_no}"
                ),
                observed_at=version.created_at,
                score_source="owner_read",
                extra={
                    "source_identity": f"artifact:{artifact.id}",
                    "artifact_id": artifact.id,
                    "artifact_version_id": version.id,
                    "file_asset_id": version.file_asset_id,
                    "file_asset_version": version.file_asset_version,
                },
            )
        )
    return chunks


def _read_career_domains(
    db,
    *,
    request: CareerDomainSourceRequest,
    intent: SearchIntent,
    user_pk: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    sections = set(request.sections)
    object_ids = set(request.object_ids)
    if "career_profile" in sections:
        try:
            profile = career_profile_service.get_career_profile(db, user_pk=user_pk)
        except career_profile_service.CareerProfileNotFoundError:
            profile = None
        if profile is not None and (
            not object_ids
            or _payload_contains_identity(profile.model_dump(mode="json"), object_ids)
        ):
            chunks.append(
                _domain_chunk(
                    intent,
                    kind="career_profile",
                    identity=profile.id,
                    title="个人详情/求职档案",
                    payload=profile.model_dump(mode="json"),
                    version=f"version:{profile.version}",
                    observed_at=profile.updated_at,
                )
            )
    if "job_opportunities" in sections:
        rows = list_job_opportunities(
            db,
            user_pk=user_pk,
            include_archived=request.include_inactive,
            limit=1000 if object_ids else request.limit,
        )
        if request.reference_kind == "job_opportunity":
            rows = [row for row in rows if str(row.id) in object_ids]
        for row in rows:
            view = JobOpportunityView.model_validate(row)
            chunks.append(
                _domain_chunk(
                    intent,
                    kind="job_opportunity",
                    identity=row.id,
                    title=f"{row.company_name} · {row.job_title}",
                    payload=view.model_dump(mode="json"),
                    version=f"updated:{row.updated_at.isoformat()}",
                    observed_at=row.updated_at,
                )
            )
    if "next_actions" in sections:
        statuses = None if request.include_inactive else {"suggested", "planned"}
        rows = list_next_actions(
            db,
            user_pk=user_pk,
            statuses=statuses,
            limit=1000 if object_ids else request.limit,
        )
        if request.reference_kind == "next_action":
            rows = [row for row in rows if str(row.id) in object_ids]
        for row in rows:
            chunks.append(
                _domain_chunk(
                    intent,
                    kind="next_action",
                    identity=row.id,
                    title=row.content[:160],
                    payload=NextActionView.model_validate(row).model_dump(mode="json"),
                    version=f"version:{row.version}",
                    observed_at=row.updated_at,
                )
            )
    if "ability_signals" in sections:
        rows = ability_signal_service.list_ability_signals(
            db,
            user_pk=user_pk,
            include_inactive=request.include_inactive,
        )[: request.limit]
        for row in rows:
            payload = row.model_dump(mode="json")
            chunks.append(
                _domain_chunk(
                    intent,
                    kind="ability_signal",
                    identity=row.id,
                    title=str(
                        payload.get("label") or payload.get("signal") or "能力信号"
                    ),
                    payload=payload,
                    version=f"version:{row.version}",
                    observed_at=row.updated_at,
                )
            )
    if "interviews" in sections:
        rows = (
            db.query(InterviewRecord)
            .filter(InterviewRecord.user_id == user_pk)
            .order_by(InterviewRecord.updated_at.desc(), InterviewRecord.id.desc())
            .limit(1000 if object_ids else request.limit)
            .all()
        )
        if request.reference_kind == "interview_record":
            rows = [row for row in rows if str(row.id) in object_ids]
        for row in rows:
            payload = {
                "id": row.id,
                "source": row.source,
                "title": row.title,
                "status": row.status,
                "job_opportunity_id": row.job_opportunity_id,
                "analysis": _json_value(row.analysis_json),
                "ability_signal_generation": row.ability_signal_generation,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "completed_at": row.completed_at,
            }
            chunks.append(
                _domain_chunk(
                    intent,
                    kind="interview_record",
                    identity=row.id,
                    title=row.title or "面试记录",
                    payload=payload,
                    version=f"updated:{row.updated_at.isoformat()}",
                    observed_at=row.updated_at,
                )
            )
    if "offers" in sections:
        rows = (
            db.query(Offer, JobOpportunity)
            .join(JobOpportunity, JobOpportunity.id == Offer.job_opportunity_id)
            .filter(Offer.user_id == user_pk, JobOpportunity.user_id == user_pk)
            .order_by(Offer.updated_at.desc(), Offer.id.asc())
            .limit(request.limit)
            .all()
        )
        for offer, opportunity in rows:
            payload = {
                "offer": OfferView.model_validate(offer).model_dump(mode="json"),
                "current_token": offer_service.current_offer_token(offer),
                "company_name": opportunity.company_name,
                "job_title": opportunity.job_title,
            }
            chunks.append(
                _domain_chunk(
                    intent,
                    kind="offer",
                    identity=offer.id,
                    title=f"{opportunity.company_name} · {opportunity.job_title}",
                    payload=payload,
                    version=str(payload["current_token"]),
                    observed_at=offer.updated_at,
                )
            )
    return chunks


def _domain_chunk(
    intent: SearchIntent,
    *,
    kind: str,
    identity: str,
    title: str,
    payload: dict[str, Any],
    version: str,
    observed_at: datetime,
) -> dict[str, Any]:
    return _source_chunk(
        intent=intent,
        identity=f"{kind}:{identity}:{version}",
        title=title,
        text=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        source_kind=kind,
        source_version=version,
        observed_at=observed_at,
        score_source="owner_read",
        extra={"source_identity": f"{kind}:{identity}"},
    )


def _source_chunk(
    *,
    intent: SearchIntent,
    identity: str,
    title: str,
    text: str,
    source_kind: str,
    source_version: str | None,
    observed_at: datetime,
    score_source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bounded, truncated = _bounded_text(text, identity=identity)
    return {
        "chunk_id": None,
        "node_id": identity,
        "document_id": identity,
        "document_title": title,
        "file_name": None,
        "category": "product_context",
        "source_kind": source_kind,
        "source_identity": identity,
        "source_version": source_version,
        "observed_at": observed_at.isoformat(),
        "page_start": None,
        "page_end": None,
        "chunk_index": 0,
        "section_title": None,
        "heading_path": None,
        "text": bounded,
        "score": 1.0,
        "score_source": score_source,
        "intent_ids": [intent.intent_id],
        "projection_truncated": truncated,
        **(extra or {}),
    }


def _bounded_text(text: str, *, identity: str) -> tuple[str, bool]:
    value = str(text or "")
    if len(value) <= _MAX_SOURCE_TEXT_CHARS:
        return value, False
    suffix = (
        "\n\n[Bounded projection truncated. Re-read the exact owner record "
        f"identity={identity} for the remainder.]"
    )
    return value[: max(0, _MAX_SOURCE_TEXT_CHARS - len(suffix))] + suffix, True


def _empty_result(intent: SearchIntent) -> RetrievalResult:
    return RetrievalResult(
        state=RetrievalState(empty_reason=EMPTY_NO_CANDIDATES),
        intents=[intent],
    )


def _query_terms(value: str) -> list[str]:
    folded = str(value or "").casefold()
    terms = re.findall(r"[a-z0-9_+#.-]{2,}|[\u4e00-\u9fff]{2,}", folded)
    expanded: list[str] = []
    for term in terms:
        expanded.append(term)
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 2:
            expanded.extend(term[index : index + 2] for index in range(len(term) - 1))
    return list(dict.fromkeys(expanded))[:30]


def _specific_terms(query: str) -> list[str]:
    return [term for term in _query_terms(query) if term not in _GENERIC_QUERY_TERMS]


def _select_relevant(
    rows: Iterable[Any],
    *,
    query: str,
    limit: int,
    renderer: Callable[[Any], str],
) -> list[Any]:
    terms = _specific_terms(query)
    values = list(rows)
    if not terms:
        return values[:limit]
    scored = [
        (
            sum(term in renderer(row).casefold() for term in terms),
            index,
            row,
        )
        for index, row in enumerate(values)
    ]
    return [
        row
        for score, _index, row in sorted(scored, key=lambda item: (-item[0], item[1]))
        if score > 0
    ][:limit]


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return utc_now()


def _payload_contains_identity(payload: Any, identities: set[str]) -> bool:
    """Match an exact admitted identity inside one owner-returned projection."""

    if isinstance(payload, dict):
        if str(payload.get("id") or "") in identities:
            return True
        return any(
            _payload_contains_identity(value, identities) for value in payload.values()
        )
    if isinstance(payload, (list, tuple)):
        return any(_payload_contains_identity(value, identities) for value in payload)
    return False


def _json_value(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


__all__ = [
    "SharedSourceBundle",
    "SourceReadStatus",
    "acquire_shared_read_only_sources",
]
