"""Rebuildable Activity Center projection over existing authoritative owners."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.agent_interaction import AgentInteraction
from app.models.application_operation import (
    ApplicationOperation,
    CareerDomainEvent,
    OperationVerification,
)
from app.models.conversation_turn import ConversationTurn
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity
from app.schemas.career_activity import ActivityObjectReference, CareerActivityEvent


_DOMAIN_DETAILS = {
    "interview_invitation_candidate_registered": "发现一条可能的面试邀请，等待确认",
    "interview_invitation_candidate_rejected": "面试邀请候选已被拒绝",
    "job_opportunity_created": "已建立求职机会",
    "interview_created": "已建立面试安排",
    "interview_schedule_updated": "面试安排已更新",
    "process_event_appended": "求职流程已记录面试安排",
    "evidence_bound": "邀请事实来源已绑定",
    "interview_invitation_confirmed": "面试邀请已确认并通过核对",
}

_OPERATION_TITLES = {
    "intake_interview_invitation_observation": "接收面试邀请来源",
    "register_interview_invitation_candidate": "登记面试邀请候选",
    "confirm_interview_invitation": "确认面试邀请",
    "reject_interview_invitation_candidate": "拒绝面试邀请候选",
}


def _refs(value: object) -> list[ActivityObjectReference]:
    if not isinstance(value, list):
        return []
    result: list[ActivityObjectReference] = []
    for item in value:
        if not isinstance(item, dict) or not item.get("kind"):
            continue
        identity = item.get("id") or item.get("object_id")
        if not identity:
            continue
        version = item.get("version")
        result.append(
            ActivityObjectReference(
                kind=str(item["kind"]),
                id=str(identity),
                version=int(version) if isinstance(version, int) else None,
            )
        )
    return result


def _cursor(occurred_at: datetime, identity: str) -> str:
    return f"{occurred_at.isoformat()}:{identity}"


def _career_label(
    refs: list[ActivityObjectReference],
    opportunities: dict[str, JobOpportunity],
    interviews: dict[str, InterviewRecord],
) -> str:
    opportunity = next(
        (opportunities.get(ref.id) for ref in refs if ref.kind == "job_opportunity"),
        None,
    )
    if opportunity is None:
        interview = next(
            (interviews.get(ref.id) for ref in refs if ref.kind == "interview"),
            None,
        )
        if interview is not None and interview.job_opportunity_id:
            opportunity = opportunities.get(interview.job_opportunity_id)
    return (
        f"{opportunity.company_name} · {opportunity.job_title}"
        if opportunity is not None
        else "求职状态更新"
    )


def list_career_activity(
    db: Session,
    *,
    user_pk: int,
    limit: int = 100,
) -> list[CareerActivityEvent]:
    """Read current activity without creating a second status owner."""

    events = (
        db.query(CareerDomainEvent)
        .filter(CareerDomainEvent.user_id == user_pk)
        .order_by(CareerDomainEvent.occurred_at.desc(), CareerDomainEvent.id.desc())
        .limit(limit)
        .all()
    )
    operations = (
        db.query(ApplicationOperation)
        .filter(ApplicationOperation.user_id == user_pk)
        .order_by(ApplicationOperation.updated_at.desc())
        .limit(limit)
        .all()
    )
    turns = (
        db.query(ConversationTurn)
        .filter(ConversationTurn.user_id == user_pk)
        .order_by(ConversationTurn.created_at.desc())
        .limit(30)
        .all()
    )
    interactions = (
        db.query(AgentInteraction)
        .join(ConversationTurn, ConversationTurn.id == AgentInteraction.turn_id)
        .filter(ConversationTurn.user_id == user_pk)
        .order_by(AgentInteraction.created_at.desc())
        .limit(30)
        .all()
    )
    verifications = {
        row.operation_id: row
        for row in db.query(OperationVerification)
        .join(
            ApplicationOperation,
            ApplicationOperation.id == OperationVerification.operation_id,
        )
        .filter(ApplicationOperation.user_id == user_pk)
        .all()
    }
    opportunity_rows = (
        db.query(JobOpportunity).filter(JobOpportunity.user_id == user_pk).all()
    )
    interview_rows = (
        db.query(InterviewRecord).filter(InterviewRecord.user_id == user_pk).all()
    )
    opportunities = {row.id: row for row in opportunity_rows}
    interviews = {row.id: row for row in interview_rows}

    projected: list[CareerActivityEvent] = []
    for row in events:
        refs = _refs(row.object_references_json)
        label = _career_label(refs, opportunities, interviews)
        projected.append(
            CareerActivityEvent(
                event_id=row.id,
                event_kind=row.event_kind,
                event_category="domain",
                schema_version=row.schema_version,
                occurred_at=row.occurred_at,
                sequence_or_cursor=f"operation:{row.operation_id}:{row.sequence}",
                user_scope=str(user_pk),
                operation_id=row.operation_id,
                object_references=refs,
                replayable=row.replayable,
                payload={
                    "projection_group": "career",
                    "title": label,
                    "detail": _DOMAIN_DETAILS.get(row.event_kind, "求职事实已更新"),
                    "status": "confirmed",
                },
            )
        )

    for row in operations:
        verification = verifications.get(row.id)
        result = row.result_json if isinstance(row.result_json, dict) else {}
        refs = _refs(
            [
                result.get("opportunity"),
                result.get("interview"),
                result.get("candidate"),
            ]
        )
        projected.append(
            CareerActivityEvent(
                event_id=f"operation:{row.id}:{row.status}",
                event_kind="operation_status_changed",
                event_category="harness",
                schema_version=1,
                occurred_at=row.updated_at,
                sequence_or_cursor=_cursor(row.updated_at, row.id),
                user_scope=str(user_pk),
                conversation_id=row.conversation_id,
                turn_id=row.turn_id,
                task_id=row.task_id,
                operation_id=row.id,
                tool_call_id=row.tool_call_id,
                interaction_id=row.interaction_id,
                object_references=refs,
                replayable=False,
                payload={
                    "projection_group": "copilot",
                    "title": _OPERATION_TITLES.get(
                        row.operation_name, row.operation_name
                    ),
                    "detail": (
                        f"Operation {row.status}"
                        + (
                            f" · verification {verification.conclusion}"
                            if verification is not None
                            else ""
                        )
                    ),
                    "status": row.status,
                    "verification": (
                        verification.conclusion if verification is not None else None
                    ),
                },
            )
        )

    for row in interactions:
        request = row.request_json if isinstance(row.request_json, dict) else {}
        facts = request.get("invitation_facts")
        title = "等待用户输入"
        if isinstance(facts, dict):
            company = str(facts.get("company_name") or "待确认公司")
            job = str(facts.get("job_title") or "面试邀请")
            title = f"{company} · {job}"
        projected.append(
            CareerActivityEvent(
                event_id=f"interaction:{row.id}:{row.version}",
                event_kind=(
                    "interaction_requested"
                    if row.status == "pending"
                    else "interaction_resolution_recorded"
                ),
                event_category="harness",
                schema_version=row.schema_version,
                occurred_at=row.resolved_at or row.created_at,
                sequence_or_cursor=_cursor(row.resolved_at or row.created_at, row.id),
                user_scope=str(user_pk),
                turn_id=row.turn_id,
                interaction_id=row.id,
                tool_call_id=row.tool_call_id,
                object_references=_refs([request.get("candidate_reference")]),
                replayable=False,
                payload={
                    "projection_group": "copilot",
                    "title": title,
                    "detail": (
                        "等待事实确认" if row.status == "pending" else "用户决定已记录"
                    ),
                    "status": row.status,
                    "interaction_kind": row.kind,
                },
            )
        )

    for row in turns:
        projected.append(
            CareerActivityEvent(
                event_id=f"turn:{row.id}:{row.dispatch_generation}:{row.status}",
                event_kind="turn_status_changed",
                event_category="harness",
                schema_version=1,
                occurred_at=row.completed_at or row.started_at or row.created_at,
                sequence_or_cursor=_cursor(
                    row.completed_at or row.started_at or row.created_at,
                    row.id,
                ),
                user_scope=str(user_pk),
                conversation_id=row.conversation_id,
                turn_id=row.id,
                object_references=_refs(row.object_references_json),
                replayable=False,
                payload={
                    "projection_group": "copilot",
                    "title": "Copilot 执行",
                    "detail": (
                        "等待用户决定"
                        if row.status == "waiting"
                        and row.waiting_reason == "interaction"
                        else f"Turn {row.status}"
                    ),
                    "status": row.status,
                },
            )
        )

    projected.sort(
        key=lambda item: (item.occurred_at, item.event_id),
        reverse=True,
    )
    return projected[:limit]


__all__ = ["list_career_activity"]
