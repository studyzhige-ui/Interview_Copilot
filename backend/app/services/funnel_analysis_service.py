"""Source-aware historical application funnel read model.

The service never writes JobOpportunity, ProcessEvent, submitted material, or
AbilitySignal.  It analyzes immutable active facts and explicitly reports
missing coverage and confounders instead of turning correlations into ability
claims.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import product
from statistics import median

from sqlalchemy.orm import Session

from app.db.types import as_utc, utc_now
from app.models.artifact import ArtifactSubmissionSnapshot
from app.models.job_opportunity import JobOpportunity, ProcessEvent
from app.schemas.career_insights import (
    FunnelAnalysis,
    FunnelCoverage,
    FunnelGroup,
    FunnelStageMetric,
)


_IN_PROCESS_KINDS = {
    "recruiter_contact",
    "assessment_invited",
    "assessment_completed",
    "hiring_step",
    "interview_scheduled",
    "interview_completed",
    "background_check_started",
}
_TERMINAL_KINDS = {
    "rejected",
    "withdrawn",
    "posting_closed",
    "offer_declined",
    "offer_accepted",
}


@dataclass(frozen=True)
class _Sample:
    opportunity: JobOpportunity
    application_event: ProcessEvent
    active_events: tuple[ProcessEvent, ...]
    directions: tuple[tuple[str, str | None], ...]
    channel: str | None
    submitted_versions: tuple[str, ...]


def analyze_funnel(
    db: Session,
    *,
    user_pk: int,
    direction_id: str | None = None,
    submitted_artifact_version_id: str | None = None,
    channel: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
) -> FunnelAnalysis:
    opportunities = (
        db.query(JobOpportunity)
        .filter(JobOpportunity.user_id == user_pk)
        .order_by(JobOpportunity.created_at.asc(), JobOpportunity.id.asc())
        .all()
    )
    samples: list[_Sample] = []
    for opportunity in opportunities:
        events = (
            db.query(ProcessEvent)
            .filter(ProcessEvent.job_opportunity_id == opportunity.id)
            .order_by(ProcessEvent.sequence.asc())
            .all()
        )
        active_ids = _active_event_ids(events)
        active_events = tuple(event for event in events if event.id in active_ids)
        applications = sorted(
            (event for event in active_events if event.kind == "application_submitted"),
            key=lambda event: (event.occurred_at, event.sequence),
        )
        if not applications:
            continue
        application = applications[0]
        occurred = as_utc(application.occurred_at)
        if occurred_from and occurred and occurred < as_utc(occurred_from):
            continue
        if occurred_to and occurred and occurred > as_utc(occurred_to):
            continue
        context = dict(application.analysis_context_json or {})
        raw_directions = context.get("directions")
        directions: tuple[tuple[str, str | None], ...] = ()
        if isinstance(raw_directions, list):
            directions = tuple(
                (str(item["id"]), str(item["label"]) if item.get("label") else None)
                for item in raw_directions
                if isinstance(item, dict) and item.get("id")
            )
        sample_channel = (
            str(context["channel"])
            if context.get("channel")
            else opportunity.source_provider
        )
        submissions = (
            db.query(ArtifactSubmissionSnapshot.artifact_version_id)
            .filter(
                ArtifactSubmissionSnapshot.user_id == user_pk,
                ArtifactSubmissionSnapshot.job_opportunity_id == opportunity.id,
            )
            .order_by(ArtifactSubmissionSnapshot.submitted_at.asc())
            .all()
        )
        versions = tuple(dict.fromkeys(row[0] for row in submissions))
        if direction_id and direction_id not in {item[0] for item in directions}:
            continue
        if (
            submitted_artifact_version_id
            and submitted_artifact_version_id not in versions
        ):
            continue
        if channel and (sample_channel or "").casefold() != channel.casefold():
            continue
        samples.append(
            _Sample(
                opportunity=opportunity,
                application_event=application,
                active_events=active_events,
                directions=directions,
                channel=sample_channel,
                submitted_versions=versions,
            )
        )

    groups: dict[
        tuple[str | None, str | None, str | None, str | None, str], list[_Sample]
    ] = defaultdict(list)
    for sample in samples:
        direction_values = sample.directions or ((None, None),)
        version_values: tuple[str | None, ...] = sample.submitted_versions or (None,)
        month = sample.application_event.occurred_at.strftime("%Y-%m")
        for direction_value, version in product(direction_values, version_values):
            key = (
                direction_value[0],
                direction_value[1],
                version,
                sample.channel,
                month,
            )
            groups[key].append(sample)

    group_views = [
        _group_view(key, group_samples)
        for key, group_samples in sorted(
            groups.items(), key=lambda item: tuple(value or "" for value in item[0])
        )
    ]
    coverage = FunnelCoverage(
        sample_count=len(samples),
        direction_snapshot_count=sum(bool(sample.directions) for sample in samples),
        submitted_material_count=sum(
            bool(sample.submitted_versions) for sample in samples
        ),
        channel_count=sum(bool(sample.channel) for sample in samples),
        jd_snapshot_count=sum(
            bool(
                sample.application_event.analysis_context_json.get(
                    "jd_snapshot_identity"
                )
            )
            for sample in samples
        ),
        outcome_count=sum(sample.opportunity.outcome is not None for sample in samples),
    )
    notes = []
    for label, count in (
        ("历史目标方向快照", coverage.direction_snapshot_count),
        ("确证的 submitted 材料版本", coverage.submitted_material_count),
        ("投递渠道", coverage.channel_count),
        ("带观察时点的 JD 快照", coverage.jd_snapshot_count),
        ("明确终局", coverage.outcome_count),
    ):
        if count < coverage.sample_count:
            notes.append(f"{label}覆盖 {count}/{coverage.sample_count} 个岗位样本")
    return FunnelAnalysis(
        generated_at=utc_now(),
        sample_job_ids=sorted(sample.opportunity.id for sample in samples),
        coverage=coverage,
        groups=group_views,
        missing_source_notes=notes,
        confounders=[
            "岗位与候选人匹配程度",
            "招聘市场与公司用人需求变化",
            "投递渠道和内推可见度",
            "投递与招聘批次时机",
            "材料表达方式及未记录的材料差异",
        ],
        interpretation_limit=(
            "漏斗只描述已保存事实之间的相关诊断信号，不构成因果证明，"
            "也不能直接归因为用户能力。同一岗位存在多个历史方向或实际提交"
            "材料版本时会进入多个细分组，各组样本不可直接相加。"
        ),
    )


def _group_view(
    key: tuple[str | None, str | None, str | None, str | None, str],
    samples: list[_Sample],
) -> FunnelGroup:
    direction_id, direction_label, version_id, channel, month = key
    sample_count = len(samples)
    stage_kinds = {
        "applied": {"application_submitted", "application_acknowledged"},
        "in_process": _IN_PROCESS_KINDS,
        "offer": {"offer_received"},
        "terminal": _TERMINAL_KINDS,
    }
    metrics: list[FunnelStageMetric] = []
    for stage, kinds in stage_kinds.items():
        waits: list[float] = []
        reached = 0
        for sample in samples:
            matching = sorted(
                (event for event in sample.active_events if event.kind in kinds),
                key=lambda event: (event.occurred_at, event.sequence),
            )
            if not matching:
                continue
            reached += 1
            wait = as_utc(matching[0].occurred_at) - as_utc(
                sample.application_event.occurred_at
            )
            waits.append(max(0.0, wait.total_seconds() / 3600))
        metrics.append(
            FunnelStageMetric(
                stage=stage,
                reached=reached,
                conversion_from_sample=(
                    reached / sample_count if sample_count else 0.0
                ),
                median_wait_hours=round(median(waits), 2) if waits else None,
            )
        )
    outcomes = Counter(sample.opportunity.outcome or "active" for sample in samples)
    return FunnelGroup(
        direction_id=direction_id,
        direction_label=direction_label,
        submitted_artifact_version_id=version_id,
        channel=channel,
        calendar_month=month,
        sample_job_ids=sorted(sample.opportunity.id for sample in samples),
        stages=metrics,
        outcomes=dict(sorted(outcomes.items())),
    )


def _active_event_ids(events: list[ProcessEvent]) -> set[str]:
    active: set[str] = set()
    inactive: set[str] = set()
    for event in reversed(events):
        if event.id in inactive:
            continue
        if event.corrects_event_id:
            inactive.add(event.corrects_event_id)
        if event.operation == "assert":
            active.add(event.id)
    return active


__all__ = ["analyze_funnel"]
