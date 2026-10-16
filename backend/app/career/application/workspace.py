"""Career workspace queries and user commands, using the existing owners."""

import json
import hashlib
from sqlalchemy import or_, func
from app.db.types import utc_now
from app.models.artifact import (
    Artifact,
    ArtifactJobRelation,
    ArtifactVersion,
    ArtifactSubmissionSnapshot,
)
from app.models.career_workspace import OpportunityDetails
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import (
    JobOpportunity,
    JobOpportunityMerge,
    NextAction,
    ProcessEvent,
)
from app.schemas.job_opportunity import (
    JobOpportunityView,
    ProcessEventView,
    NextActionView,
)
from app.schemas.artifact import ArtifactVersionView, ArtifactView
from app.career.application import process, artifacts

STAGE_LABELS = {
    "saved": "待投递",
    "applied": "已投递",
    "screening": "筛选 / 测评",
    "interview": "面试",
    "in_process": "进行中",
    "offer": "Offer",
    "closed": "已结束",
}


def create_job(db, user_pk, command):
    from app.schemas.job_opportunity import OpportunityCreate
    from app.schemas.job_description_snapshot import JobDescriptionSnapshotFromProductUI
    from app.career.application.job_descriptions import (
        create_job_description_snapshot,
        normalize_job_description_url,
        JobDescriptionSnapshotError,
    )

    if command.source_url:
        try:
            normalize_job_description_url(command.source_url)
        except JobDescriptionSnapshotError as exc:
            raise process.CareerProcessError(str(exc)) from exc
    # A stable timestamp makes a repeated create command idempotent.
    existing = (
        db.query(JobOpportunity)
        .filter_by(user_id=user_pk, idempotency_key=command.operation_key)
        .one_or_none()
    )
    timestamp = (
        process._first_event(db, existing.id).occurred_at if existing else utc_now()
    )
    admission = process.create_job_opportunity(
        db,
        user_pk=user_pk,
        command=OpportunityCreate(
            company_name=command.company_name,
            job_title=command.job_title,
            location=command.location or None,
            source_url=command.source_url or None,
            entry_reason="explicit_tracking",
            occurred_at=timestamp,
            source_kind="user_assertion",
            source_identity=command.operation_key,
            source_version=hashlib.sha256(
                json.dumps(
                    command.model_dump(exclude={"operation_key"}), sort_keys=True
                ).encode()
            ).hexdigest(),
            source_description="保存岗位",
            idempotency_key=command.operation_key,
        ),
    )
    if command.description:
        create_job_description_snapshot(
            db,
            user_pk=user_pk,
            opportunity_id=admission.opportunity.id,
            command=JobDescriptionSnapshotFromProductUI(
                source_identity=command.operation_key,
                source_version="1",
                original_url=command.source_url,
                observed_at=timestamp,
                provider="product_ui",
                canonical_content=command.description,
                idempotency_key=command.operation_key,
            ),
        )
    return detail(db, user_pk, admission.opportunity.id)


def job_query(db, user_pk, q="", hidden=False):
    """Visible canonical opportunities shared by the board and home projection."""
    duplicates = db.query(JobOpportunityMerge.duplicate_opportunity_id).filter(
        JobOpportunityMerge.user_id == user_pk, JobOpportunityMerge.status == "active"
    )
    query = db.query(JobOpportunity).filter(
        JobOpportunity.user_id == user_pk, ~JobOpportunity.id.in_(duplicates)
    )
    if q.strip():
        pattern = (
            "%"
            + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        query = query.filter(
            or_(
                *[
                    field.ilike(pattern, escape="\\")
                    for field in (
                        JobOpportunity.company_name,
                        JobOpportunity.job_title,
                        JobOpportunity.location,
                    )
                ]
            )
        )
    return query.outerjoin(
        OpportunityDetails, OpportunityDetails.opportunity_id == JobOpportunity.id
    ).filter(
        OpportunityDetails.hidden_at.is_not(None)
        if hidden
        else OpportunityDetails.hidden_at.is_(None)
    )


def job_view(job, details, actions, interviews=()):
    result = JobOpportunityView.model_validate(job).model_dump(mode="json")
    result.update(
        version=job.version,
        stage=job.pipeline_stage,
        notes=details.notes if details else "",
        contacts=details.contacts if details else [],
        hidden=bool(details and details.hidden_at),
    )
    pending = [a for a in actions if a.status in {"planned", "suggested"}]
    pending.sort(key=lambda a: a.starts_at or a.due_at or a.created_at)
    result["next_action"] = (
        NextActionView.model_validate(pending[0]).model_dump(mode="json")
        if pending and not job.outcome
        else None
    )
    upcoming = sorted(
        (
            i
            for i in interviews
            if i.scheduled_start_at and i.scheduled_start_at >= utc_now()
        ),
        key=lambda i: i.scheduled_start_at,
    )
    result["next_interview"] = (
        {
            "id": upcoming[0].id,
            "title": upcoming[0].stage_label or upcoming[0].title,
            "starts_at": upcoming[0].scheduled_start_at,
        }
        if upcoming and not job.outcome
        else None
    )
    return result


def list_jobs(
    db, user_pk, q="", stage=None, closed=False, hidden=False, offset=0, limit=30
):
    query = job_query(db, user_pk, q, hidden=hidden)
    counts = {s: 0 for s in STAGE_LABELS}
    for value, count in (
        query.with_entities(
            JobOpportunity.pipeline_stage, func.count(JobOpportunity.id)
        )
        .group_by(JobOpportunity.pipeline_stage)
        .all()
    ):
        counts[value] = count
    if not closed:
        query = query.filter(JobOpportunity.pipeline_stage != "closed")
    if stage:
        query = query.filter(JobOpportunity.pipeline_stage == stage)
    total = query.count()
    jobs = (
        query.order_by(JobOpportunity.updated_at.desc(), JobOpportunity.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    ids = [j.id for j in jobs]
    owner_ids = {job_id: job_id for job_id in ids}
    for merge in (
        db.query(JobOpportunityMerge)
        .filter(
            JobOpportunityMerge.user_id == user_pk,
            JobOpportunityMerge.status == "active",
            JobOpportunityMerge.canonical_opportunity_id.in_(ids),
        )
        .all()
    ):
        owner_ids[merge.duplicate_opportunity_id] = merge.canonical_opportunity_id
    actions, interviews = {}, {}
    for row in (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.user_id == user_pk,
            InterviewRecord.job_opportunity_id.in_(owner_ids),
        )
        .all()
    ):
        interviews.setdefault(owner_ids[row.job_opportunity_id], []).append(row)
    for row in (
        db.query(NextAction)
        .filter(
            NextAction.user_id == user_pk, NextAction.job_opportunity_id.in_(owner_ids)
        )
        .all()
    ):
        actions.setdefault(owner_ids[row.job_opportunity_id], []).append(row)
    details = {
        r.opportunity_id: r
        for r in db.query(OpportunityDetails)
        .filter(OpportunityDetails.opportunity_id.in_(ids))
        .all()
    }
    return {
        "items": [
            job_view(
                j,
                details.get(j.id),
                actions.get(j.id, []),
                interviews.get(j.id, []),
            )
            for j in jobs
        ],
        "total": total,
        "counts": counts,
    }


def owned_job(db, user_pk, job_id):
    # Resolve reversible duplicate links without changing either source history.
    seen = set()
    while job_id not in seen:
        seen.add(job_id)
        merge = (
            db.query(JobOpportunityMerge)
            .filter_by(
                user_id=user_pk, duplicate_opportunity_id=job_id, status="active"
            )
            .one_or_none()
        )
        if not merge:
            return process._locked_opportunity(db, user_pk, job_id)
        job_id = merge.canonical_opportunity_id
    raise process.CareerProcessError("岗位合并关系存在循环")


def detail(db, user_pk, job_id):
    job = owned_job(db, user_pk, job_id)
    sources = (
        db.query(JobOpportunity)
        .join(
            JobOpportunityMerge,
            JobOpportunityMerge.duplicate_opportunity_id == JobOpportunity.id,
        )
        .filter(
            JobOpportunity.user_id == user_pk,
            JobOpportunityMerge.user_id == user_pk,
            JobOpportunityMerge.canonical_opportunity_id == job.id,
            JobOpportunityMerge.status == "active",
        )
        .all()
    )
    ids = [job.id, *[source.id for source in sources]]
    events = (
        db.query(ProcessEvent)
        .filter(ProcessEvent.job_opportunity_id.in_(ids))
        .order_by(ProcessEvent.occurred_at, ProcessEvent.sequence)
        .all()
    )
    actions = (
        db.query(NextAction)
        .filter(NextAction.user_id == user_pk, NextAction.job_opportunity_id.in_(ids))
        .all()
    )
    interviews = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.user_id == user_pk,
            InterviewRecord.job_opportunity_id.in_(ids),
        )
        .all()
    )
    result = job_view(job, db.get(OpportunityDetails, job.id), actions, interviews)
    result["merged_sources"] = [
        {
            "id": source.id,
            "company_name": source.company_name,
            "job_title": source.job_title,
        }
        for source in sources
    ]
    active = process._active_event_ids(events)
    result["events"] = [
        {
            **ProcessEventView.model_validate(e).model_dump(mode="json"),
            "active": e.id in active,
        }
        for e in events
    ]
    result["actions"] = [
        NextActionView.model_validate(a).model_dump(mode="json") for a in actions
    ]
    jobs_by_id = {j.id: j for j in [job, *sources]}
    result["interviews"] = [
        {
            "id": i.id,
            "title": i.title,
            "source": i.source,
            "schedule_version": i.schedule_version,
            "opportunity": {
                "id": i.job_opportunity_id,
                "version": jobs_by_id[i.job_opportunity_id].version,
                "company_name": jobs_by_id[i.job_opportunity_id].company_name,
                "job_title": jobs_by_id[i.job_opportunity_id].job_title,
            },
            "scheduled_start_at": i.scheduled_start_at,
            "scheduled_end_at": i.scheduled_end_at,
            "scheduled_location": i.scheduled_location,
            "meeting_url": i.meeting_url,
            "stage_label": i.stage_label,
        }
        for i in interviews
    ]
    relations = (
        db.query(Artifact, ArtifactVersion)
        .join(ArtifactJobRelation, ArtifactJobRelation.artifact_id == Artifact.id)
        .join(ArtifactVersion, ArtifactVersion.artifact_id == Artifact.id)
        .filter(
            Artifact.user_id == user_pk, ArtifactJobRelation.job_opportunity_id.in_(ids)
        )
        .order_by(ArtifactVersion.version_no.desc())
        .all()
    )
    by_artifact = {}
    for artifact, version in relations:
        if artifact.id not in by_artifact:
            by_artifact[artifact.id] = ArtifactView(
                id=artifact.id,
                kind=artifact.kind,
                archived_at=artifact.archived_at,
                current_version=ArtifactVersionView.model_validate(version),
            ).model_dump(mode="json")
    result["documents"] = list(by_artifact.values())
    submissions = (
        db.query(ArtifactSubmissionSnapshot, ArtifactVersion)
        .join(
            ArtifactVersion,
            ArtifactVersion.id == ArtifactSubmissionSnapshot.artifact_version_id,
        )
        .filter(
            ArtifactSubmissionSnapshot.user_id == user_pk,
            ArtifactSubmissionSnapshot.job_opportunity_id.in_(ids),
        )
        .all()
    )
    result["submissions"] = [
        {
            "id": s.id,
            "submitted_at": s.submitted_at,
            "version": ArtifactVersionView.model_validate(v).model_dump(mode="json"),
        }
        for s, v in submissions
    ]
    return result


def edit_job(db, user_pk, job_id, command):
    job = owned_job(db, user_pk, job_id)
    if job.version != command.expected_version:
        raise process.ProcessEventConflictError("岗位已在别处更新，请刷新后重试")
    url = command.source_url.strip()
    if url:
        from app.career.application.job_descriptions import (
            normalize_job_description_url,
        )

        try:
            normalized = normalize_job_description_url(url)
        except ValueError as exc:
            raise process.CareerProcessError(str(exc)) from exc
    else:
        normalized = None
    job.company_name, job.job_title = command.company_name, command.job_title
    job.location, job.source_url, job.normalized_source_url = (
        command.location or None,
        url or None,
        normalized,
    )
    job.version += 1
    job.updated_at = utc_now()
    metadata = db.get(OpportunityDetails, job.id) or OpportunityDetails(
        opportunity_id=job.id
    )
    metadata.notes = command.notes
    metadata.contacts = [c.model_dump() for c in command.contacts]
    metadata.hidden_at = utc_now() if command.hidden else None
    db.add_all([metadata, job])
    db.flush()
    return detail(db, user_pk, job.id)


def change_stage(db, user_pk, job_id, command):
    job = owned_job(db, user_pk, job_id)
    identity = "workspace:" + command.operation_key
    fingerprint = json.dumps(
        command.model_dump(mode="json", exclude={"expected_version"}),
        sort_keys=True,
        ensure_ascii=False,
    )
    existing = process._event_by_idempotency(db, job.id, identity)
    if existing:
        if (existing.analysis_context_json or {}).get("command") != fingerprint:
            raise process.CareerIdempotencyConflictError(identity)
        return detail(db, user_pk, job.id)
    if job.version != command.expected_version:
        raise process.ProcessEventConflictError("岗位已在别处更新，请刷新后重试")
    if command.stage == "closed" and not command.outcome:
        raise process.CareerProcessError("请选择结束原因")
    if command.stage != "closed" and command.outcome:
        raise process.CareerProcessError("只有结束申请才能设置结果")
    if command.version_ids and command.stage != "applied":
        raise process.CareerProcessError("投递材料只能随实际投递记录保存")
    kind = {
        "saved": "tracking_started",
        "applied": "application_submitted",
        "screening": "recruiter_contact",
        "interview": "hiring_step",
        "in_process": "hiring_step",
        "offer": "offer_received",
    }.get(command.stage)
    if command.stage == "closed":
        kind = {
            "rejected": "rejected",
            "withdrawn": "withdrawn",
            "posting_closed": "posting_closed",
            "declined_offer": "offer_declined",
            "accepted": "offer_accepted",
        }[command.outcome]
    context = {"command": fingerprint}
    if command.stage != "closed":
        context["pipeline_stage"] = command.stage
    if command.stage == "applied":
        context.update(
            process._application_analysis_context(
                db,
                job,
                application_channel=command.channel,
                jd_snapshot_id=None,
                jd_snapshot_version=None,
            )
        )
        context["submitted_version_ids"] = command.version_ids
    process._insert_event(
        db,
        opportunity=job,
        operation="assert",
        kind=kind,
        occurred_at=command.occurred_at,
        observed_at=None,
        source_kind="user_assertion",
        source_identity=identity,
        source_version=None,
        description=command.note.strip() or STAGE_LABELS[command.stage],
        step_summary=STAGE_LABELS[command.stage],
        application_channel=command.channel,
        corrects_event_id=None,
        idempotency_key=identity,
        analysis_context_json=context,
    )
    for index, version_id in enumerate(dict.fromkeys(command.version_ids)):
        version = (
            db.query(ArtifactVersion)
            .join(Artifact)
            .filter(ArtifactVersion.id == version_id, Artifact.user_id == user_pk)
            .one_or_none()
        )
        if version is None:
            raise process.CareerObjectNotFoundError(version_id)
        artifacts.record_product_ui_confirmed_submission(
            db,
            user_pk=user_pk,
            operation_key=f"{command.operation_key}:{index}",
            artifact_id=version.artifact_id,
            artifact_version_id=version.id,
            submitted_at=command.occurred_at,
            job_opportunity_id=job.id,
            job_owner_checker=lambda session, owner, kind, ref: (
                kind == "job_opportunity" and owner == user_pk and ref == job.id
            ),
        )
    process._rebuild_projection(db, job)
    return detail(db, user_pk, job.id)
