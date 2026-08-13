"""Application Service for append-only JobOpportunity JD snapshots.

The source boundary is deliberately concrete. A snapshot is accepted only
from an exact owned completed ``read_url``/``search_jobs`` ToolResult, or from
an explicit typed first-party product UI command. There is no generic Source
object, registry, confidence layer, or model-authored provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agent_execution import AgentToolCall
from app.models.job_description_snapshot import JobDescriptionSnapshot
from app.models.job_opportunity import JobOpportunity
from app.schemas.job_description_snapshot import (
    JobDescriptionSnapshotCreate,
    JobDescriptionSnapshotFromProductUI,
    JobDescriptionSnapshotFromToolResult,
)


MAX_CANONICAL_JD_CHARS = 120_000
_JD_TOOL_NAMES = frozenset({"read_url", "search_jobs"})
_URL_KEYS = (
    "url",
    "job_url",
    "source_url",
    "final_url",
    "hosted_url",
    "apply_url",
)
_CONTENT_KEYS = (
    "canonical_content",
    "job_description",
    "description_text",
    "description_plain",
    "description",
    "content",
    "markdown",
    "text",
    "jd",
)
_PROVIDER_KEYS = ("provider", "source", "site", "platform")


class JobDescriptionSnapshotError(ValueError):
    """Base class for deterministic snapshot rejection."""


class JobDescriptionSnapshotNotFoundError(JobDescriptionSnapshotError):
    """The opportunity/snapshot/source is absent or outside owner scope."""


class JobDescriptionSnapshotIdempotencyConflictError(JobDescriptionSnapshotError):
    """An idempotency identity was reused with different captured content."""


class JobDescriptionSnapshotSourceError(JobDescriptionSnapshotError):
    """A source does not prove an exact complete JD observation."""


def create_job_description_snapshot(
    db: Session,
    *,
    user_pk: int,
    opportunity_id: str,
    command: JobDescriptionSnapshotCreate,
) -> JobDescriptionSnapshot:
    """Append a verified JD observation and return its immutable row."""

    opportunity = _locked_opportunity(db, user_pk, opportunity_id)
    original_url = command.original_url.strip()
    normalized_url = normalize_job_description_url(original_url)
    if (
        opportunity.normalized_source_url
        and opportunity.normalized_source_url != normalized_url
    ):
        raise JobDescriptionSnapshotSourceError(
            "JD URL does not match the owned JobOpportunity"
        )

    if isinstance(command, JobDescriptionSnapshotFromToolResult):
        material = _material_from_tool_result(
            db,
            user_pk=user_pk,
            command=command,
            normalized_url=normalized_url,
        )
        canonical_content = material["canonical_content"]
        provider = material["provider"]
        source_identity = material["source_identity"]
        source_version = material["source_version"]
    elif isinstance(command, JobDescriptionSnapshotFromProductUI):
        canonical_content = canonicalize_job_description(command.canonical_content)
        provider = _provider(command.provider)
        source_identity = command.source_identity.strip()
        source_version = command.source_version.strip()
    else:  # pragma: no cover - discriminated Pydantic union is exhaustive
        raise JobDescriptionSnapshotSourceError("unsupported JD snapshot source")

    checksum = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
    fingerprint = _fingerprint(
        original_url=original_url,
        normalized_url=normalized_url,
        observed_at=command.observed_at,
        provider=provider,
        checksum=checksum,
        source_kind=command.source_kind,
        source_identity=source_identity,
        source_version=source_version,
    )
    idempotency_key = command.idempotency_key.strip()
    existing = (
        db.query(JobDescriptionSnapshot)
        .filter(
            JobDescriptionSnapshot.job_opportunity_id == opportunity.id,
            JobDescriptionSnapshot.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.creation_fingerprint != fingerprint:
            raise JobDescriptionSnapshotIdempotencyConflictError(idempotency_key)
        return existing

    version = (
        int(
            db.query(func.max(JobDescriptionSnapshot.version))
            .filter(JobDescriptionSnapshot.job_opportunity_id == opportunity.id)
            .scalar()
            or 0
        )
        + 1
    )
    row = JobDescriptionSnapshot(
        job_opportunity_id=opportunity.id,
        version=version,
        original_url=original_url,
        normalized_url=normalized_url,
        observed_at=command.observed_at,
        provider=provider,
        canonical_content=canonical_content,
        content_checksum=checksum,
        source_kind=command.source_kind,
        source_identity=source_identity,
        source_version=source_version,
        idempotency_key=idempotency_key,
        creation_fingerprint=fingerprint,
    )
    if opportunity.source_url is None:
        opportunity.source_url = original_url
        opportunity.normalized_source_url = normalized_url
    if opportunity.source_provider is None:
        opportunity.source_provider = provider
    db.add_all([opportunity, row])
    db.flush()
    return row


def current_job_description_snapshot(
    db: Session,
    *,
    user_pk: int,
    opportunity_id: str,
    at_or_before: datetime | None = None,
) -> JobDescriptionSnapshot | None:
    """Return the newest owned JD snapshot available at the specified time."""

    opportunity = _owned_opportunity(db, user_pk, opportunity_id)
    query = db.query(JobDescriptionSnapshot).filter(
        JobDescriptionSnapshot.job_opportunity_id == opportunity.id
    )
    if at_or_before is not None:
        query = query.filter(JobDescriptionSnapshot.observed_at <= at_or_before)
    return query.order_by(
        JobDescriptionSnapshot.observed_at.desc(),
        JobDescriptionSnapshot.version.desc(),
    ).first()


def require_owned_job_description_snapshot(
    db: Session,
    *,
    user_pk: int,
    opportunity_id: str,
    snapshot_id: str,
    version: int | None = None,
) -> JobDescriptionSnapshot:
    query = (
        db.query(JobDescriptionSnapshot)
        .join(
            JobOpportunity,
            JobOpportunity.id == JobDescriptionSnapshot.job_opportunity_id,
        )
        .filter(
            JobDescriptionSnapshot.id == snapshot_id,
            JobDescriptionSnapshot.job_opportunity_id == opportunity_id,
            JobOpportunity.user_id == user_pk,
        )
    )
    if version is not None:
        query = query.filter(JobDescriptionSnapshot.version == version)
    row = query.one_or_none()
    if row is None:
        raise JobDescriptionSnapshotNotFoundError(snapshot_id)
    return row


def list_job_description_snapshots(
    db: Session,
    *,
    user_pk: int,
    opportunity_id: str,
) -> list[JobDescriptionSnapshot]:
    opportunity = _owned_opportunity(db, user_pk, opportunity_id)
    return (
        db.query(JobDescriptionSnapshot)
        .filter(JobDescriptionSnapshot.job_opportunity_id == opportunity.id)
        .order_by(JobDescriptionSnapshot.version.asc())
        .all()
    )


def canonicalize_job_description(value: str) -> str:
    """Produce a bounded, deterministic text snapshot without summarizing it."""

    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = re.sub(r"\n{4,}", "\n\n\n", normalized)
    if not normalized:
        raise JobDescriptionSnapshotSourceError("JD content is empty")
    if len(normalized) > MAX_CANONICAL_JD_CHARS:
        raise JobDescriptionSnapshotSourceError(
            f"JD content exceeds {MAX_CANONICAL_JD_CHARS} characters"
        )
    return normalized


def normalize_job_description_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise JobDescriptionSnapshotSourceError(
            "original_url must be an absolute HTTP(S) URL"
        )
    if parsed.username or parsed.password:
        raise JobDescriptionSnapshotSourceError("original_url contains credentials")
    hostname = parsed.hostname.lower()
    port = parsed.port
    if port and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query_names = [name for name, _value in query_pairs]
    if len(query_names) == len(set(query_names)):
        query_pairs.sort()
    return urlunsplit(
        (
            parsed.scheme.lower(),
            hostname,
            path,
            urlencode(query_pairs),
            "",
        )
    )


def _material_from_tool_result(
    db: Session,
    *,
    user_pk: int,
    command: JobDescriptionSnapshotFromToolResult,
    normalized_url: str,
) -> dict[str, str]:
    rows = (
        db.query(AgentToolCall)
        .filter(
            AgentToolCall.user_id == user_pk,
            AgentToolCall.session_id == command.tool_session_id,
            AgentToolCall.call_id == command.source_identity,
            AgentToolCall.status == "completed",
            AgentToolCall.tool_name.in_(sorted(_JD_TOOL_NAMES)),
        )
        .all()
    )
    if len(rows) != 1:
        raise JobDescriptionSnapshotNotFoundError(
            "owned completed JD ToolResult not found or ambiguous"
        )
    call = rows[0]
    result = call.result_json
    if (
        not isinstance(result, Mapping)
        or result.get("error")
        or result.get("truncated")
    ):
        raise JobDescriptionSnapshotSourceError(
            "ToolResult is failed, truncated, or not structured"
        )

    matches: list[tuple[str, str | None]] = []
    for candidate in _walk_mappings(result):
        candidate_url = _first_string(candidate, _URL_KEYS)
        if candidate_url is None and candidate is result:
            candidate_url = _first_string(call.arguments_json or {}, _URL_KEYS)
        if candidate_url is None:
            continue
        try:
            candidate_normalized_url = normalize_job_description_url(candidate_url)
        except JobDescriptionSnapshotSourceError:
            continue
        if candidate_normalized_url != normalized_url:
            continue
        content = _first_string(candidate, _CONTENT_KEYS)
        if content is None:
            continue
        provider = _first_string(candidate, _PROVIDER_KEYS)
        matches.append((canonicalize_job_description(content), provider))

    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) != 1:
        raise JobDescriptionSnapshotSourceError(
            "ToolResult does not contain exactly one matching complete JD detail"
        )
    canonical_content, provider_value = unique_matches[0]
    completed_at = call.completed_at
    if completed_at is None:
        raise JobDescriptionSnapshotSourceError("completed ToolResult has no timestamp")
    provider = _provider(
        provider_value or urlsplit(normalized_url).hostname or call.tool_name
    )
    return {
        "canonical_content": canonical_content,
        "provider": provider,
        "source_identity": f"agent_tool_call:{call.id}",
        "source_version": (
            f"generation:{int(call.dispatch_generation or 1)}:"
            f"completed:{completed_at.isoformat()}"
        )[:128],
    }


def _walk_mappings(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _first_string(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _provider(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise JobDescriptionSnapshotSourceError("provider is required")
    if len(normalized) > 80:
        raise JobDescriptionSnapshotSourceError("provider exceeds 80 characters")
    return normalized


def _fingerprint(**values: Any) -> str:
    encoded = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: (
            value.isoformat() if isinstance(value, datetime) else str(value)
        ),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _locked_opportunity(
    db: Session,
    user_pk: int,
    opportunity_id: str,
) -> JobOpportunity:
    row = (
        db.query(JobOpportunity)
        .filter(
            JobOpportunity.id == opportunity_id,
            JobOpportunity.user_id == user_pk,
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if row is None:
        raise JobDescriptionSnapshotNotFoundError(opportunity_id)
    return row


def _owned_opportunity(
    db: Session,
    user_pk: int,
    opportunity_id: str,
) -> JobOpportunity:
    row = (
        db.query(JobOpportunity)
        .filter(
            JobOpportunity.id == opportunity_id,
            JobOpportunity.user_id == user_pk,
        )
        .one_or_none()
    )
    if row is None:
        raise JobDescriptionSnapshotNotFoundError(opportunity_id)
    return row


__all__ = [
    "MAX_CANONICAL_JD_CHARS",
    "JobDescriptionSnapshotError",
    "JobDescriptionSnapshotIdempotencyConflictError",
    "JobDescriptionSnapshotNotFoundError",
    "JobDescriptionSnapshotSourceError",
    "canonicalize_job_description",
    "create_job_description_snapshot",
    "current_job_description_snapshot",
    "list_job_description_snapshots",
    "normalize_job_description_url",
    "require_owned_job_description_snapshot",
]
