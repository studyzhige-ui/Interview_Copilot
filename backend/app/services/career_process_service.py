"""Application Service for JobOpportunity, ProcessEvent, and NextAction.

All callers (future UI endpoints, Agent tools, and connector adapters) use the
same commands here. The caller owns the transaction; this module flushes but
never commits, so an opportunity and its first fact, or a terminal fact and
the deterministic action closures it causes, share one atomic boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.db.types import as_utc, utc_now
from app.models.career_profile import CareerProfile, CareerProfileDirection
from app.models.artifact import Artifact
from app.models.interview_record import InterviewRecord
from app.models.job_description_snapshot import JobDescriptionSnapshot
from app.models.job_opportunity import (
    NEXT_ACTION_TRANSITION_SOURCE_KINDS,
    PROCESS_EVENT_KINDS,
    PROCESS_SOURCE_KINDS,
    JobOpportunity,
    JobOpportunityDirectionLink,
    JobOpportunityMerge,
    NextAction,
    ProcessEvent,
)
from app.models.offer import Offer
from app.schemas.job_opportunity import (
    NextActionClose,
    NextActionCreate,
    NextActionEdit,
    NextActionTransition,
    OpportunityCreate,
    OpportunityDirectionSelection,
    OpportunityDirectionsReplace,
    OpportunityMergeCreate,
    OpportunityMergeRetract,
    ProcessEventAppend,
    ProcessEventCorrection,
)
from app.services.job_description_snapshot_service import (
    current_job_description_snapshot,
)


_ENTRY_EVENT = {
    "explicit_tracking": "tracking_started",
    "targeted_preparation": "preparation_started",
    "user_confirmed_application": "application_submitted",
    "verified_submission": "application_submitted",
}

_EVENT_PHASE = {
    "tracking_started": "pending_application",
    "preparation_started": "pending_application",
    "application_submitted": "applied",
    "application_acknowledged": "applied",
    "recruiter_contact": "in_process",
    "assessment_invited": "in_process",
    "assessment_completed": "in_process",
    "hiring_step": "in_process",
    "interview_scheduled": "in_process",
    "interview_completed": "in_process",
    "background_check_started": "in_process",
    "offer_received": "offer",
}
_PHASE_RANK = {
    "pending_application": 0,
    "applied": 1,
    "in_process": 2,
    "offer": 3,
}
_EVENT_OUTCOME = {
    "rejected": "rejected",
    "withdrawn": "withdrawn",
    "posting_closed": "posting_closed",
    "offer_declined": "declined_offer",
    "offer_accepted": "accepted",
}
_DEFAULT_STEP = {
    "tracking_started": "已加入跟踪",
    "preparation_started": "正在针对岗位准备",
    "application_submitted": "已确认投递",
    "application_acknowledged": "招聘方已收到申请",
    "recruiter_contact": "招聘方沟通中",
    "assessment_invited": "在线测评待完成",
    "assessment_completed": "已完成测评，等待结果",
    "hiring_step": "招聘流程推进中",
    "interview_scheduled": "面试已安排",
    "interview_completed": "面试已完成，等待结果",
    "background_check_started": "背调进行中",
    "offer_received": "已收到 Offer",
    "rejected": "招聘方明确未通过",
    "withdrawn": "已确认退出流程",
    "posting_closed": "申请流程已明确关闭",
    "offer_declined": "已拒绝 Offer",
    "offer_accepted": "已接受 Offer",
}


class CareerProcessError(ValueError):
    """Base class for deterministic command rejection."""


class CareerObjectNotFoundError(CareerProcessError):
    """The object is absent or outside the caller's ownership boundary."""


class CareerIdempotencyConflictError(CareerProcessError):
    """A stable command identity was reused with different content."""


class OpportunityArchivedError(CareerProcessError):
    """A terminal opportunity cannot accept ordinary process updates."""


class OpportunityDirectionConflictError(CareerProcessError):
    """A direction relation command used a stale CAS token or unsafe overwrite."""


class OpportunityMergeConflictError(CareerProcessError):
    """A duplicate relation is stale, cyclic, or conflicts with current state."""


class ProcessEventConflictError(CareerProcessError):
    """A proposed fact or correction violates the append-only timeline."""


class NextActionTransitionError(CareerProcessError):
    """A NextAction command is unsupported by its current lifecycle state."""


@dataclass(frozen=True)
class OpportunityAdmission:
    opportunity: JobOpportunity
    created: bool
    initial_event: ProcessEvent | None


def create_job_opportunity(
    db: Session,
    *,
    user_pk: int,
    command: OpportunityCreate,
) -> OpportunityAdmission:
    """Admit one concrete role into long-term state for an allowed reason.

    Exact application identities always resolve to the existing line. Exact
    active job ids/URLs also reuse the active line unless the user explicitly
    confirmed a new application after a terminal process.
    """

    company_name = _text(command.company_name, "company_name", 200)
    job_title = _text(command.job_title, "job_title", 300)
    source_provider = _optional_text(command.source_provider, 80, lower=True)
    external_job_id = _optional_text(command.external_job_id, 200)
    external_application_id = _optional_text(command.external_application_id, 200)
    source_url = _optional_text(command.source_url, 4_000)
    normalized_url = _normalize_url(source_url) if source_url else None
    idempotency_key = _optional_text(command.idempotency_key, 200)
    directions = _validated_direction_selections(
        db,
        user_pk=user_pk,
        selections=command.directions,
    )

    if (external_job_id or external_application_id) and not source_provider:
        raise CareerProcessError(
            "source_provider is required with an external job/application id"
        )

    if idempotency_key:
        existing = (
            db.query(JobOpportunity)
            .options(selectinload(JobOpportunity.direction_links))
            .filter(
                JobOpportunity.user_id == user_pk,
                JobOpportunity.idempotency_key == idempotency_key,
            )
            .one_or_none()
        )
        if existing is not None:
            first_event = _first_event(db, existing.id)
            if (
                not _same_opportunity_command(
                    existing,
                    company_name=company_name,
                    job_title=job_title,
                    source_provider=source_provider,
                    external_job_id=external_job_id,
                    external_application_id=external_application_id,
                    normalized_url=normalized_url,
                )
                or first_event is None
                or not _same_event(
                    first_event,
                    operation="assert",
                    kind=_ENTRY_EVENT[command.entry_reason],
                    occurred_at=command.occurred_at,
                    source_kind=command.source_kind,
                    source_identity=command.source_identity,
                    source_version=command.source_version,
                    description=command.source_description,
                    step_summary=None,
                    corrects_event_id=None,
                )
                or (
                    directions
                    and not _same_direction_links(
                        existing.direction_links,
                        directions,
                        source_kind=command.source_kind,
                        source_identity=command.source_identity,
                        exact_source=True,
                    )
                )
            ):
                raise CareerIdempotencyConflictError(idempotency_key)
            return OpportunityAdmission(existing, False, first_event)

    existing = _find_strong_match(
        db,
        user_pk=user_pk,
        source_provider=source_provider,
        external_job_id=external_job_id,
        external_application_id=external_application_id,
        normalized_url=normalized_url,
        skip_terminal_job_match=command.reapplication_confirmed,
    )
    event_kind = _ENTRY_EVENT[command.entry_reason]
    if existing is not None:
        if existing.outcome is not None:
            # A terminal job/application identity remains historical unless
            # reapplication_confirmed excluded it from the match above.
            return OpportunityAdmission(existing, False, _first_event(db, existing.id))
        _enrich_identity(
            existing,
            location=command.location,
            team=command.team,
            source_url=source_url,
            normalized_url=normalized_url,
            source_provider=source_provider,
            external_job_id=external_job_id,
            external_application_id=external_application_id,
        )
        if directions and not _same_direction_links(
            existing.direction_links,
            directions,
        ):
            if existing.direction_version != 0:
                raise OpportunityDirectionConflictError(
                    "opportunity already has versioned direction links; "
                    "use the direction replacement command"
                )
            _replace_direction_links(
                db,
                opportunity=existing,
                selections=directions,
                source_kind=command.source_kind,
                source_identity=command.source_identity,
            )
        initial_event = None
        if event_kind == "application_submitted":
            initial_event = append_confirmed_process_event(
                db,
                user_pk=user_pk,
                opportunity_id=existing.id,
                command=ProcessEventAppend(
                    kind=event_kind,
                    occurred_at=command.occurred_at,
                    source_kind=command.source_kind,
                    source_identity=command.source_identity,
                    source_version=command.source_version,
                    description=command.source_description,
                    idempotency_key=_entry_event_key(command),
                ),
            )
        db.add(existing)
        db.flush()
        return OpportunityAdmission(existing, False, initial_event)

    opportunity = JobOpportunity(
        user_id=user_pk,
        company_name=company_name,
        job_title=job_title,
        location=_optional_text(command.location, 200),
        team=_optional_text(command.team, 200),
        source_url=source_url,
        normalized_source_url=normalized_url,
        source_provider=source_provider,
        external_job_id=external_job_id,
        external_application_id=external_application_id,
        idempotency_key=idempotency_key,
    )
    db.add(opportunity)
    db.flush()
    if directions:
        _replace_direction_links(
            db,
            opportunity=opportunity,
            selections=directions,
            source_kind=command.source_kind,
            source_identity=command.source_identity,
        )
    initial_event = append_confirmed_process_event(
        db,
        user_pk=user_pk,
        opportunity_id=opportunity.id,
        command=ProcessEventAppend(
            kind=event_kind,
            occurred_at=command.occurred_at,
            source_kind=command.source_kind,
            source_identity=command.source_identity,
            source_version=command.source_version,
            description=command.source_description,
            idempotency_key=_entry_event_key(command),
        ),
    )
    return OpportunityAdmission(opportunity, True, initial_event)


def replace_job_opportunity_directions(
    db: Session,
    *,
    user_pk: int,
    opportunity_id: str,
    command: OpportunityDirectionsReplace,
) -> JobOpportunity:
    """CAS-replace current direction links without rewriting process history."""

    opportunity = _locked_opportunity(db, user_pk, opportunity_id)
    if opportunity.outcome is not None:
        raise OpportunityArchivedError(opportunity.id)
    if opportunity.direction_version != command.expected_version:
        raise OpportunityDirectionConflictError(
            f"expected direction version {command.expected_version}, "
            f"current version is {opportunity.direction_version}"
        )
    if command.source_kind not in PROCESS_SOURCE_KINDS:
        raise CareerProcessError(
            f"invalid direction source kind: {command.source_kind}"
        )
    source_identity = _text(command.source_identity, "source_identity", 256)
    selections = _validated_direction_selections(
        db,
        user_pk=user_pk,
        selections=command.directions,
    )
    if _same_direction_links(opportunity.direction_links, selections):
        return opportunity
    _replace_direction_links(
        db,
        opportunity=opportunity,
        selections=selections,
        source_kind=command.source_kind,
        source_identity=source_identity,
    )
    return opportunity


def append_confirmed_process_event(
    db: Session,
    *,
    user_pk: int,
    opportunity_id: str,
    command: ProcessEventAppend,
) -> ProcessEvent:
    """Append one already-confirmed fact and rebuild the current projection."""

    opportunity = _locked_opportunity(db, user_pk, opportunity_id)
    idempotency_key = command.idempotency_key or _natural_event_key(
        command.source_kind,
        command.source_identity,
        command.kind,
        None,
    )
    existing = _event_by_idempotency(db, opportunity.id, idempotency_key)
    if existing is not None:
        if not _same_event(
            existing,
            operation="assert",
            kind=command.kind,
            occurred_at=command.occurred_at,
            source_kind=command.source_kind,
            source_identity=command.source_identity,
            source_version=command.source_version,
            description=command.description,
            step_summary=command.step_summary,
            application_channel=command.application_channel,
            corrects_event_id=None,
        ):
            raise CareerIdempotencyConflictError(idempotency_key)
        return existing
    if opportunity.outcome is not None:
        raise OpportunityArchivedError(opportunity.id)
    if command.kind == "hiring_step" and not _optional_text(command.step_summary, 300):
        raise ProcessEventConflictError("hiring_step requires step_summary")

    jd_snapshot = None
    if command.kind == "application_submitted":
        jd_snapshot = current_job_description_snapshot(
            db,
            user_pk=user_pk,
            opportunity_id=opportunity.id,
            at_or_before=command.occurred_at,
        )

    event_row = _insert_event(
        db,
        opportunity=opportunity,
        operation="assert",
        kind=command.kind,
        occurred_at=command.occurred_at,
        observed_at=command.observed_at,
        source_kind=command.source_kind,
        source_identity=command.source_identity,
        source_version=command.source_version,
        description=command.description,
        step_summary=command.step_summary,
        application_channel=command.application_channel,
        corrects_event_id=None,
        jd_snapshot_id=jd_snapshot.id if jd_snapshot is not None else None,
        jd_snapshot_version=jd_snapshot.version if jd_snapshot is not None else None,
        idempotency_key=idempotency_key,
    )
    _rebuild_projection(db, opportunity)
    return event_row


def correct_process_event(
    db: Session,
    *,
    user_pk: int,
    opportunity_id: str,
    target_event_id: str,
    command: ProcessEventCorrection,
) -> ProcessEvent:
    """Append a replacement or retraction; the target row remains unchanged."""

    opportunity = _locked_opportunity(db, user_pk, opportunity_id)
    operation = "assert" if command.replacement_kind else "retract"
    kind = command.replacement_kind or "retraction"
    idempotency_key = command.idempotency_key or _natural_event_key(
        command.source_kind,
        command.source_identity,
        kind,
        target_event_id,
    )
    existing = _event_by_idempotency(db, opportunity.id, idempotency_key)
    if existing is not None:
        if not _same_event(
            existing,
            operation=operation,
            kind=kind,
            occurred_at=command.occurred_at,
            source_kind=command.source_kind,
            source_identity=command.source_identity,
            source_version=command.source_version,
            description=command.description,
            step_summary=command.step_summary,
            application_channel=command.application_channel,
            corrects_event_id=target_event_id,
        ):
            raise CareerIdempotencyConflictError(idempotency_key)
        return existing

    target = (
        db.query(ProcessEvent)
        .filter(
            ProcessEvent.id == target_event_id,
            ProcessEvent.job_opportunity_id == opportunity.id,
        )
        .one_or_none()
    )
    if target is None:
        raise CareerObjectNotFoundError(target_event_id)
    if target.corrects_event_id is not None or target.operation != "assert":
        raise ProcessEventConflictError(
            "a correction record cannot itself be corrected in the minimal model"
        )
    active_ids = _active_event_ids(_events(db, opportunity.id))
    if target.id not in active_ids:
        raise ProcessEventConflictError("target ProcessEvent is already inactive")
    if operation == "retract" and len(active_ids) == 1:
        raise ProcessEventConflictError(
            "cannot retract the only fact that admitted the opportunity"
        )
    if kind == "hiring_step" and not _optional_text(command.step_summary, 300):
        raise ProcessEventConflictError("hiring_step requires step_summary")

    correction_context: dict[str, object] | None = None
    if operation == "assert" and kind == "application_submitted":
        # A replacement of an historical application carries its historical
        # snapshot.  If the corrected source was not previously an application,
        # leave coverage unknown instead of back-labelling it with today's
        # CareerProfile.  An explicitly corrected channel may safely replace
        # just that one historical dimension.
        correction_context = (
            dict(target.analysis_context_json or {})
            if target.kind == "application_submitted"
            else {}
        )
        if command.application_channel is not None:
            correction_context["channel"] = _text(
                command.application_channel,
                "application_channel",
                160,
            )

    correction = _insert_event(
        db,
        opportunity=opportunity,
        operation=operation,
        kind=kind,
        occurred_at=command.occurred_at,
        observed_at=command.observed_at,
        source_kind=command.source_kind,
        source_identity=command.source_identity,
        source_version=command.source_version,
        description=command.description,
        step_summary=command.step_summary,
        application_channel=command.application_channel,
        jd_snapshot_id=target.jd_snapshot_id,
        jd_snapshot_version=target.jd_snapshot_version,
        corrects_event_id=target.id,
        idempotency_key=idempotency_key,
        # A correction must not silently re-label an historical application
        # with today's profile/direction state.  Replacing an application fact
        # therefore carries forward the snapshot captured by that fact.
        analysis_context_json=correction_context,
    )
    _rebuild_projection(db, opportunity)
    return correction


def create_next_action(
    db: Session,
    *,
    user_pk: int,
    command: NextActionCreate,
) -> NextAction:
    """Create one durable action only when it has cross-turn decision value."""

    content = _text(command.content, "content", 2_000)
    (
        opportunity_id,
        interview_record_id,
        offer_id,
        artifact_id,
    ) = _validated_action_associations(
        db,
        user_pk=user_pk,
        job_opportunity_id=command.job_opportunity_id,
        interview_record_id=command.interview_record_id,
        offer_id=command.offer_id,
        artifact_id=command.artifact_id,
    )
    if command.status == "planned" and command.source_kind not in {
        "user_request",
        "copilot_preference",
        "process_event",
    }:
        raise NextActionTransitionError(
            "agent/process suggestions must be accepted before becoming planned"
        )
    if command.status == "suggested" and command.source_kind not in {
        "process_event",
        "agent_suggestion",
        "offer",
    }:
        raise NextActionTransitionError(
            "user requests and confirmed preferences are already planned"
        )

    idempotency_key = command.idempotency_key or _natural_action_key(
        command.source_kind,
        command.source_identity,
        content,
    )
    existing = (
        db.query(NextAction)
        .filter(
            NextAction.user_id == user_pk,
            NextAction.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if existing is not None:
        expected_opportunity_id = opportunity_id or (
            existing.job_opportunity_id
            if command.source_kind == "process_event"
            else None
        )
        if not _same_action(existing, command, content, expected_opportunity_id):
            raise CareerIdempotencyConflictError(idempotency_key)
        return existing

    source_event = None
    if command.source_kind == "process_event":
        source_event = _owned_active_event(db, user_pk, command.source_identity)
        if opportunity_id and opportunity_id != source_event.job_opportunity_id:
            raise CareerProcessError("process event belongs to another opportunity")
        opportunity_id = source_event.job_opportunity_id
        if offer_id:
            linked_offer = db.get(Offer, offer_id)
            if (
                linked_offer is None
                or linked_offer.job_opportunity_id != opportunity_id
            ):
                raise CareerProcessError(
                    "process event and Offer associations belong to different opportunities"
                )
        if command.status == "planned" and not (
            source_event.kind == "interview_scheduled" and command.time_kind == "fixed"
        ):
            raise NextActionTransitionError(
                "only a confirmed fixed interview event may directly form a "
                "planned process-event action"
            )

    opportunity = None
    if opportunity_id:
        opportunity = _owned_opportunity(db, user_pk, opportunity_id)
        if opportunity.outcome is not None:
            raise OpportunityArchivedError(opportunity.id)

    # A second UI/Agent command that names the same active action is a read,
    # not a duplicate row.  Time and typed associations remain part of the
    # identity, so recurring or otherwise distinct actions are unaffected.
    duplicate = _find_active_action_duplicate(
        db,
        user_pk=user_pk,
        command=command,
        content=content,
        opportunity_id=opportunity_id,
        interview_record_id=interview_record_id,
        offer_id=offer_id,
        artifact_id=artifact_id,
    )
    if duplicate is not None:
        return duplicate

    now = utc_now()
    action = NextAction(
        user_id=user_pk,
        job_opportunity_id=opportunity_id,
        interview_record_id=interview_record_id,
        offer_id=offer_id,
        artifact_id=artifact_id,
        content=content,
        status=command.status,
        time_kind=command.time_kind,
        starts_at=command.starts_at,
        ends_at=command.ends_at,
        due_at=command.due_at,
        original_time_text=_optional_text(command.original_time_text, 300),
        source_timezone=_optional_text(command.source_timezone, 80),
        source_kind=command.source_kind,
        source_identity=_text(command.source_identity, "source_identity", 256),
        source_version=_optional_text(command.source_version, 128),
        reminder_at=command.reminder_at,
        reminder_next_attempt_at=command.reminder_at,
        reminder_channel=command.reminder_channel,
        idempotency_key=idempotency_key,
    )
    if command.status == "planned":
        action.planned_at = now
        action.planned_source_kind = {
            "user_request": "user_assertion",
            "process_event": "process_event",
            "copilot_preference": "copilot_preference",
        }[command.source_kind]
        action.planned_source_identity = action.source_identity
        action.planned_source_version = action.source_version
    db.add(action)
    db.flush()
    return action


def edit_next_action(
    db: Session,
    *,
    user_pk: int,
    action_id: str,
    command: NextActionEdit,
) -> NextAction:
    """CAS-replace user-editable details without changing lifecycle facts."""

    action = _locked_action(db, user_pk, action_id)
    if action.version != command.expected_version:
        raise NextActionTransitionError(
            f"expected action version {command.expected_version}, "
            f"current version is {action.version}"
        )
    if action.status not in {"suggested", "planned"}:
        raise NextActionTransitionError(f"cannot edit action in {action.status}")
    if command.reminder_at is not None and action.status != "planned":
        raise NextActionTransitionError("only planned actions may schedule reminders")
    associations = _validated_action_associations(
        db,
        user_pk=user_pk,
        job_opportunity_id=command.job_opportunity_id,
        interview_record_id=command.interview_record_id,
        offer_id=command.offer_id,
        artifact_id=command.artifact_id,
    )
    content = _text(command.content, "content", 2_000)
    values = {
        "content": content,
        "time_kind": command.time_kind,
        "job_opportunity_id": associations[0],
        "interview_record_id": associations[1],
        "offer_id": associations[2],
        "artifact_id": associations[3],
        "starts_at": command.starts_at,
        "ends_at": command.ends_at,
        "due_at": command.due_at,
        "original_time_text": _optional_text(command.original_time_text, 300),
        "source_timezone": _optional_text(command.source_timezone, 80),
        "reminder_at": command.reminder_at,
        "reminder_next_attempt_at": command.reminder_at,
        "reminder_channel": command.reminder_channel,
        "reminder_delivered_at": None,
        "reminder_dismissed_at": None,
    }
    if all(getattr(action, field) == value for field, value in values.items()):
        return action
    for field, value in values.items():
        setattr(action, field, value)
    action.version += 1
    action.updated_at = utc_now()
    db.add(action)
    db.flush()
    return action


def plan_next_action(
    db: Session,
    *,
    user_pk: int,
    action_id: str,
    transition: NextActionTransition,
) -> NextAction:
    action = _locked_action(db, user_pk, action_id)
    if transition.source_kind not in {"user_assertion", "copilot_preference"}:
        raise NextActionTransitionError(
            "planning requires user or confirmed preference"
        )
    if action.status == "planned":
        _require_same_transition(
            action.planned_source_kind,
            action.planned_source_identity,
            action.planned_source_version,
            transition,
        )
        return action
    if action.status != "suggested":
        raise NextActionTransitionError(f"cannot plan action in {action.status}")
    _ensure_action_opportunity_active(db, action)
    action.status = "planned"
    action.planned_at = utc_now()
    action.planned_source_kind = transition.source_kind
    action.planned_source_identity = transition.source_identity
    action.planned_source_version = transition.source_version
    action.updated_at = utc_now()
    action.version += 1
    db.add(action)
    db.flush()
    return action


def complete_next_action(
    db: Session,
    *,
    user_pk: int,
    action_id: str,
    transition: NextActionTransition,
) -> NextAction:
    action = _locked_action(db, user_pk, action_id)
    if transition.source_kind == "copilot_preference":
        raise NextActionTransitionError("a preference cannot prove completion")
    if action.status == "done":
        _require_same_transition(
            action.resolution_source_kind,
            action.resolution_source_identity,
            action.resolution_source_version,
            transition,
        )
        return action
    if action.status not in {"suggested", "planned"}:
        raise NextActionTransitionError(f"cannot complete action in {action.status}")
    _validate_resolution_source(db, user_pk, action, transition)
    _resolve_action(action, status="done", transition=transition)
    db.add(action)
    db.flush()
    return action


def close_next_action(
    db: Session,
    *,
    user_pk: int,
    action_id: str,
    transition: NextActionClose,
) -> NextAction:
    action = _locked_action(db, user_pk, action_id)
    if transition.source_kind == "copilot_preference":
        raise NextActionTransitionError("a preference cannot close an existing action")
    if action.status == "closed":
        _require_same_transition(
            action.resolution_source_kind,
            action.resolution_source_identity,
            action.resolution_source_version,
            transition,
        )
        if action.close_reason != transition.reason.strip():
            raise CareerIdempotencyConflictError(action.id)
        return action
    if action.status not in {"suggested", "planned"}:
        raise NextActionTransitionError(f"cannot close action in {action.status}")
    _validate_resolution_source(db, user_pk, action, transition)
    _resolve_action(
        action,
        status="closed",
        transition=transition,
        close_reason=_text(transition.reason, "reason", 300),
    )
    db.add(action)
    db.flush()
    return action


def list_job_opportunities(
    db: Session,
    *,
    user_pk: int,
    include_archived: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[JobOpportunity]:
    query = (
        db.query(JobOpportunity)
        .options(selectinload(JobOpportunity.direction_links))
        .filter(JobOpportunity.user_id == user_pk)
    )
    if not include_archived:
        query = query.filter(JobOpportunity.outcome.is_(None))
    return (
        query.order_by(JobOpportunity.updated_at.desc(), JobOpportunity.id.asc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 500)))
        .all()
    )


def list_opportunity_merges(
    db: Session,
    *,
    user_pk: int,
    include_retracted: bool = False,
) -> list[JobOpportunityMerge]:
    query = db.query(JobOpportunityMerge).filter(JobOpportunityMerge.user_id == user_pk)
    if not include_retracted:
        query = query.filter(JobOpportunityMerge.status == "active")
    return query.order_by(JobOpportunityMerge.created_at.desc()).all()


def suggest_opportunity_merge_candidates(
    db: Session,
    *,
    user_pk: int,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Return deterministic candidates; never merge from a heuristic alone."""

    rows = list_job_opportunities(
        db,
        user_pk=user_pk,
        include_archived=True,
        limit=max(2, min(limit, 200)),
    )
    active_duplicates = {
        row.duplicate_opportunity_id
        for row in list_opportunity_merges(db, user_pk=user_pk)
    }
    candidates: list[dict[str, object]] = []
    for left_index, left in enumerate(rows):
        if left.id in active_duplicates:
            continue
        for right in rows[left_index + 1 :]:
            if right.id in active_duplicates:
                continue
            reasons: list[str] = []
            if (
                left.source_provider
                and left.source_provider == right.source_provider
                and left.external_job_id
                and left.external_job_id == right.external_job_id
            ):
                reasons.append("same_provider_job_identity")
            if (
                left.normalized_source_url
                and left.normalized_source_url == right.normalized_source_url
            ):
                reasons.append("same_normalized_source_url")
            if (
                left.company_name.casefold() == right.company_name.casefold()
                and left.job_title.casefold() == right.job_title.casefold()
                and (left.location or "").casefold()
                == (right.location or "").casefold()
            ):
                reasons.append("same_company_title_location")
            if reasons:
                older, newer = sorted(
                    (left, right), key=lambda row: (row.created_at, row.id)
                )
                candidates.append(
                    {
                        "duplicate_opportunity_id": newer.id,
                        "canonical_opportunity_id": older.id,
                        "reasons": reasons,
                    }
                )
    return candidates[:100]


def merge_job_opportunities(
    db: Session,
    *,
    user_pk: int,
    command: OpportunityMergeCreate,
) -> JobOpportunityMerge:
    duplicate = _owned_opportunity(db, user_pk, command.duplicate_opportunity_id)
    canonical = _owned_opportunity(db, user_pk, command.canonical_opportunity_id)
    if duplicate.id == canonical.id:
        raise OpportunityMergeConflictError("an opportunity cannot merge into itself")

    operation_key = _text(command.operation_key, "operation_key", 200)
    reason = _text(command.reason, "reason", 2_000)
    existing_by_key = (
        db.query(JobOpportunityMerge)
        .filter(
            JobOpportunityMerge.user_id == user_pk,
            JobOpportunityMerge.operation_key == operation_key,
        )
        .one_or_none()
    )
    if existing_by_key is not None:
        if (
            existing_by_key.duplicate_opportunity_id == duplicate.id
            and existing_by_key.canonical_opportunity_id == canonical.id
            and existing_by_key.reason == reason
        ):
            return existing_by_key
        raise CareerIdempotencyConflictError(operation_key)

    active = (
        db.query(JobOpportunityMerge)
        .filter(
            JobOpportunityMerge.user_id == user_pk,
            JobOpportunityMerge.status == "active",
            or_(
                JobOpportunityMerge.duplicate_opportunity_id.in_(
                    [duplicate.id, canonical.id]
                ),
                JobOpportunityMerge.canonical_opportunity_id == duplicate.id,
            ),
        )
        .all()
    )
    if active:
        raise OpportunityMergeConflictError(
            "an opportunity already participates in an active merge chain"
        )

    row = JobOpportunityMerge(
        user_id=user_pk,
        duplicate_opportunity_id=duplicate.id,
        canonical_opportunity_id=canonical.id,
        operation_key=operation_key,
        reason=reason,
        confirmation_source_identity=f"product_ui:{operation_key}",
    )
    db.add(row)
    db.flush()
    return row


def retract_job_opportunity_merge(
    db: Session,
    *,
    user_pk: int,
    merge_id: str,
    command: OpportunityMergeRetract,
) -> JobOpportunityMerge:
    row = (
        db.query(JobOpportunityMerge)
        .filter(
            JobOpportunityMerge.id == merge_id,
            JobOpportunityMerge.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise CareerObjectNotFoundError("job opportunity merge")
    operation_key = _text(command.operation_key, "operation_key", 200)
    reason = _text(command.reason, "reason", 2_000)
    if row.status == "retracted":
        if (
            row.retraction_operation_key == operation_key
            and row.retraction_reason == reason
        ):
            return row
        raise OpportunityMergeConflictError("merge is already retracted")
    if row.version != command.expected_version:
        raise OpportunityMergeConflictError(
            f"expected merge version {command.expected_version}, current {row.version}"
        )
    row.status = "retracted"
    row.version += 1
    row.retraction_operation_key = operation_key
    row.retraction_reason = reason
    row.retracted_at = utc_now()
    db.add(row)
    db.flush()
    return row


def list_process_events(
    db: Session,
    *,
    user_pk: int,
    opportunity_id: str,
) -> list[ProcessEvent]:
    _owned_opportunity(db, user_pk, opportunity_id)
    return _events(db, opportunity_id)


def list_next_actions(
    db: Session,
    *,
    user_pk: int,
    statuses: set[str] | None = None,
    limit: int = 200,
) -> list[NextAction]:
    query = db.query(NextAction).filter(NextAction.user_id == user_pk)
    if statuses:
        invalid = statuses - {"suggested", "planned", "done", "closed"}
        if invalid:
            raise CareerProcessError(f"invalid NextAction statuses: {sorted(invalid)}")
        query = query.filter(NextAction.status.in_(sorted(statuses)))
    return (
        query.order_by(NextAction.updated_at.desc(), NextAction.id.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )


def _insert_event(
    db: Session,
    *,
    opportunity: JobOpportunity,
    operation: str,
    kind: str,
    occurred_at: datetime,
    observed_at: datetime | None,
    source_kind: str,
    source_identity: str,
    source_version: str | None,
    description: str,
    step_summary: str | None,
    application_channel: str | None,
    corrects_event_id: str | None,
    jd_snapshot_id: str | None = None,
    jd_snapshot_version: int | None = None,
    idempotency_key: str,
    analysis_context_json: dict[str, object] | None = None,
) -> ProcessEvent:
    if kind not in PROCESS_EVENT_KINDS or source_kind not in PROCESS_SOURCE_KINDS:
        raise ProcessEventConflictError("unsupported ProcessEvent kind/source")
    next_sequence = (
        int(
            db.query(func.max(ProcessEvent.sequence))
            .filter(ProcessEvent.job_opportunity_id == opportunity.id)
            .scalar()
            or 0
        )
        + 1
    )
    event_row = ProcessEvent(
        job_opportunity_id=opportunity.id,
        sequence=next_sequence,
        operation=operation,
        kind=kind,
        occurred_at=occurred_at,
        observed_at=observed_at or utc_now(),
        source_kind=source_kind,
        source_identity=_text(source_identity, "source_identity", 256),
        source_version=_optional_text(source_version, 128),
        description=_text(description, "description", 10_000),
        step_summary=_optional_text(step_summary, 300),
        analysis_context_json=(
            dict(analysis_context_json)
            if analysis_context_json is not None
            else (
                _application_analysis_context(
                    db,
                    opportunity,
                    application_channel=application_channel,
                    jd_snapshot_id=jd_snapshot_id,
                    jd_snapshot_version=jd_snapshot_version,
                )
                if kind == "application_submitted" and operation == "assert"
                else {}
            )
        ),
        jd_snapshot_id=jd_snapshot_id,
        jd_snapshot_version=jd_snapshot_version,
        corrects_event_id=corrects_event_id,
        idempotency_key=_text(idempotency_key, "idempotency_key", 300),
    )
    db.add(event_row)
    db.flush()
    return event_row


def _rebuild_projection(db: Session, opportunity: JobOpportunity) -> None:
    events = _events(db, opportunity.id)
    active_ids = _active_event_ids(events)
    active_events = [event_row for event_row in events if event_row.id in active_ids]
    if not active_events:
        raise ProcessEventConflictError("an opportunity must retain an admission fact")

    phase = "pending_application"
    phase_event: ProcessEvent | None = None
    terminal_event: ProcessEvent | None = None
    for event_row in active_events:
        event_phase = _EVENT_PHASE.get(event_row.kind)
        if event_phase and (
            _PHASE_RANK[event_phase] > _PHASE_RANK[phase]
            or (
                _PHASE_RANK[event_phase] == _PHASE_RANK[phase]
                and (phase_event is None or event_row.sequence > phase_event.sequence)
            )
        ):
            phase = event_phase
            phase_event = event_row
        if event_row.kind in _EVENT_OUTCOME:
            terminal_event = event_row

    opportunity.phase = phase
    opportunity.outcome = (
        _EVENT_OUTCOME[terminal_event.kind] if terminal_event is not None else None
    )
    display_event = terminal_event or phase_event or active_events[-1]
    opportunity.current_step = (
        display_event.step_summary or _DEFAULT_STEP[display_event.kind]
    )
    opportunity.archived_at = (
        terminal_event.observed_at if terminal_event is not None else None
    )
    opportunity.last_event_at = max(row.occurred_at for row in events)
    opportunity.updated_at = utc_now()
    db.add(opportunity)

    if terminal_event is not None:
        for action in (
            db.query(NextAction)
            .filter(
                NextAction.job_opportunity_id == opportunity.id,
                NextAction.status.in_(("suggested", "planned")),
            )
            .with_for_update()
            .all()
        ):
            transition = NextActionTransition(
                source_kind="process_event",
                source_identity=terminal_event.id,
            )
            _resolve_action(
                action,
                status="closed",
                transition=transition,
                close_reason=f"job_terminal:{opportunity.outcome}",
            )
            db.add(action)
    db.flush()


def _resolve_action(
    action: NextAction,
    *,
    status: str,
    transition: NextActionTransition,
    close_reason: str | None = None,
) -> None:
    now = utc_now()
    action.status = status
    action.resolved_at = now
    action.resolution_source_kind = transition.source_kind
    action.resolution_source_identity = _text(
        transition.source_identity,
        "source_identity",
        256,
    )
    action.resolution_source_version = _optional_text(transition.source_version, 128)
    action.close_reason = close_reason
    action.updated_at = now
    action.version += 1


def _validate_resolution_source(
    db: Session,
    user_pk: int,
    action: NextAction,
    transition: NextActionTransition,
) -> None:
    if transition.source_kind not in NEXT_ACTION_TRANSITION_SOURCE_KINDS:
        raise NextActionTransitionError("unsupported transition source")
    if transition.source_kind == "process_event":
        event_row = _owned_active_event(db, user_pk, transition.source_identity)
        if (
            action.job_opportunity_id
            and event_row.job_opportunity_id != action.job_opportunity_id
        ):
            raise NextActionTransitionError(
                "completion ProcessEvent belongs to another opportunity"
            )


def _ensure_action_opportunity_active(db: Session, action: NextAction) -> None:
    if not action.job_opportunity_id:
        return
    opportunity = db.get(JobOpportunity, action.job_opportunity_id)
    if opportunity is None or opportunity.user_id != action.user_id:
        raise CareerObjectNotFoundError(action.job_opportunity_id)
    if opportunity.outcome is not None:
        raise OpportunityArchivedError(opportunity.id)


def _require_same_transition(
    stored_kind: str | None,
    stored_identity: str | None,
    stored_version: str | None,
    transition: NextActionTransition,
) -> None:
    if (
        stored_kind != transition.source_kind
        or stored_identity != transition.source_identity.strip()
        or stored_version != _optional_text(transition.source_version, 128)
    ):
        raise CareerIdempotencyConflictError(transition.source_identity)


def _locked_opportunity(
    db: Session,
    user_pk: int,
    opportunity_id: str,
) -> JobOpportunity:
    row = (
        db.query(JobOpportunity)
        .options(selectinload(JobOpportunity.direction_links))
        .filter(
            JobOpportunity.id == opportunity_id,
            JobOpportunity.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise CareerObjectNotFoundError(opportunity_id)
    return row


def _validated_direction_selections(
    db: Session,
    *,
    user_pk: int,
    selections: list[OpportunityDirectionSelection],
) -> list[OpportunityDirectionSelection]:
    normalized = [
        OpportunityDirectionSelection(
            direction_id=_text(item.direction_id, "direction_id", 36),
            match_reason=_text(item.match_reason, "match_reason", 2_000),
        )
        for item in selections
    ]
    direction_ids = [item.direction_id for item in normalized]
    if len(direction_ids) != len(set(direction_ids)):
        raise CareerProcessError("directions must not contain duplicates")
    if not direction_ids:
        return normalized

    rows = (
        db.query(CareerProfileDirection)
        .join(
            CareerProfile,
            CareerProfile.id == CareerProfileDirection.career_profile_id,
        )
        .filter(
            CareerProfile.user_id == user_pk,
            CareerProfileDirection.id.in_(direction_ids),
        )
        .all()
    )
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(direction_ids):
        # Cross-user direction ids fail closed without revealing ownership.
        raise CareerObjectNotFoundError("career profile direction")
    return normalized


def _same_direction_links(
    links: list[JobOpportunityDirectionLink],
    selections: list[OpportunityDirectionSelection],
    *,
    source_kind: str | None = None,
    source_identity: str | None = None,
    exact_source: bool = False,
) -> bool:
    ordered = sorted(links, key=lambda item: item.position)
    if len(ordered) != len(selections):
        return False
    normalized_identity = (
        source_identity.strip() if source_identity is not None else None
    )
    for position, (link, selection) in enumerate(zip(ordered, selections, strict=True)):
        if (
            link.position != position
            or link.career_profile_direction_id != selection.direction_id
            or link.match_reason != selection.match_reason
        ):
            return False
        if exact_source and (
            link.source_kind != source_kind
            or link.source_identity != normalized_identity
        ):
            return False
    return True


def _replace_direction_links(
    db: Session,
    *,
    opportunity: JobOpportunity,
    selections: list[OpportunityDirectionSelection],
    source_kind: str,
    source_identity: str,
) -> None:
    confirmed_at = utc_now()
    normalized_identity = _text(source_identity, "source_identity", 256)
    opportunity.direction_links.clear()
    # Flush removals before reusing the per-opportunity position uniqueness key.
    db.flush()
    opportunity.direction_links.extend(
        JobOpportunityDirectionLink(
            career_profile_direction_id=selection.direction_id,
            position=position,
            source_kind=source_kind,
            source_identity=normalized_identity,
            match_reason=selection.match_reason,
            confirmed_at=confirmed_at,
        )
        for position, selection in enumerate(selections)
    )
    opportunity.direction_version = int(opportunity.direction_version or 0) + 1
    opportunity.updated_at = confirmed_at
    db.add(opportunity)
    db.flush()


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
        raise CareerObjectNotFoundError(opportunity_id)
    return row


def _locked_action(db: Session, user_pk: int, action_id: str) -> NextAction:
    row = (
        db.query(NextAction)
        .filter(NextAction.id == action_id, NextAction.user_id == user_pk)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise CareerObjectNotFoundError(action_id)
    return row


def _validated_action_associations(
    db: Session,
    *,
    user_pk: int,
    job_opportunity_id: str | None,
    interview_record_id: str | None,
    offer_id: str | None,
    artifact_id: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    job_id = _optional_text(job_opportunity_id, 35)
    interview_id = _optional_text(interview_record_id, 128)
    normalized_offer_id = _optional_text(offer_id, 35)
    normalized_artifact_id = _optional_text(artifact_id, 128)

    job = _owned_opportunity(db, user_pk, job_id) if job_id else None
    if job is not None and job.outcome is not None:
        raise OpportunityArchivedError(job.id)

    interview = None
    if interview_id:
        interview = (
            db.query(InterviewRecord)
            .filter(
                InterviewRecord.id == interview_id,
                InterviewRecord.user_id == user_pk,
            )
            .one_or_none()
        )
        if interview is None:
            raise CareerObjectNotFoundError(interview_id)

    offer = None
    if normalized_offer_id:
        offer = (
            db.query(Offer)
            .filter(Offer.id == normalized_offer_id, Offer.user_id == user_pk)
            .one_or_none()
        )
        if offer is None:
            raise CareerObjectNotFoundError(normalized_offer_id)

    if normalized_artifact_id:
        artifact = (
            db.query(Artifact)
            .filter(
                Artifact.id == normalized_artifact_id,
                Artifact.user_id == user_pk,
            )
            .one_or_none()
        )
        if artifact is None:
            raise CareerObjectNotFoundError(normalized_artifact_id)

    related_job_ids = {
        value
        for value in (
            job_id,
            interview.job_opportunity_id if interview is not None else None,
            offer.job_opportunity_id if offer is not None else None,
        )
        if value
    }
    if len(related_job_ids) > 1:
        raise CareerProcessError(
            "typed NextAction associations belong to different opportunities"
        )
    # An action attached through Interview/Offer must not bypass terminal-line
    # sealing simply because the optional direct job link was omitted.
    related_job_id = next(iter(related_job_ids), None)
    if related_job_id and job is None:
        related_job = _owned_opportunity(db, user_pk, related_job_id)
        if related_job.outcome is not None:
            raise OpportunityArchivedError(related_job.id)

    # Interview and Offer already have one canonical opportunity owner.  Keep
    # that relationship explicit on the action even when a caller only sent the
    # typed association, so terminal projection sealing and funnel reads cannot
    # accidentally miss it.
    return (
        related_job_id,
        interview_id,
        normalized_offer_id,
        normalized_artifact_id,
    )


def _find_active_action_duplicate(
    db: Session,
    *,
    user_pk: int,
    command: NextActionCreate,
    content: str,
    opportunity_id: str | None,
    interview_record_id: str | None,
    offer_id: str | None,
    artifact_id: str | None,
) -> NextAction | None:
    candidates = (
        db.query(NextAction)
        .filter(
            NextAction.user_id == user_pk,
            NextAction.status == command.status,
            NextAction.content == content,
        )
        .order_by(NextAction.created_at.asc(), NextAction.id.asc())
        .all()
    )
    for action in candidates:
        if (
            action.job_opportunity_id == opportunity_id
            and action.interview_record_id == interview_record_id
            and action.offer_id == offer_id
            and action.artifact_id == artifact_id
            and action.time_kind == command.time_kind
            and as_utc(action.starts_at) == as_utc(command.starts_at)
            and as_utc(action.ends_at) == as_utc(command.ends_at)
            and as_utc(action.due_at) == as_utc(command.due_at)
            and as_utc(action.reminder_at) == as_utc(command.reminder_at)
            and action.reminder_channel == command.reminder_channel
        ):
            return action
    return None


def _verified_application_snapshot_identity(
    db: Session,
    *,
    user_id: int,
    opportunity_id: str,
    snapshot_id: str | None,
    snapshot_version: int | None,
) -> dict[str, object] | None:
    """Return an exact owner-verified JD identity for an event being inserted."""

    if snapshot_id is None or snapshot_version is None:
        return None
    snapshot = (
        db.query(JobDescriptionSnapshot)
        .join(
            JobOpportunity,
            JobOpportunity.id == JobDescriptionSnapshot.job_opportunity_id,
        )
        .filter(
            JobOpportunity.user_id == user_id,
            JobDescriptionSnapshot.id == snapshot_id,
            JobDescriptionSnapshot.version == snapshot_version,
            JobDescriptionSnapshot.job_opportunity_id == opportunity_id,
        )
        .one_or_none()
    )
    if snapshot is None:
        return None
    return {
        "id": snapshot.id,
        "version": snapshot.version,
        "content_checksum": snapshot.content_checksum,
        "observed_at": snapshot.observed_at.isoformat(),
    }


def _application_analysis_context(
    db: Session,
    opportunity: JobOpportunity,
    *,
    application_channel: str | None = None,
    jd_snapshot_id: str | None = None,
    jd_snapshot_version: int | None = None,
) -> dict[str, object]:
    profile = (
        db.query(CareerProfile)
        .filter(CareerProfile.user_id == opportunity.user_id)
        .one_or_none()
    )
    direction_ids = [
        link.career_profile_direction_id
        for link in sorted(opportunity.direction_links, key=lambda row: row.position)
    ]
    labels = {
        row.id: row.label
        for row in (
            db.query(CareerProfileDirection)
            .filter(CareerProfileDirection.id.in_(direction_ids))
            .all()
            if direction_ids
            else []
        )
    }
    return {
        "career_profile_version": int(profile.version) if profile is not None else None,
        "directions": [
            {"id": direction_id, "label": labels.get(direction_id)}
            for direction_id in direction_ids
        ],
        "channel": _optional_text(application_channel, 160)
        or opportunity.source_provider,
        "job_source_url": opportunity.source_url,
        "jd_snapshot_identity": _verified_application_snapshot_identity(
            db,
            user_id=opportunity.user_id,
            opportunity_id=opportunity.id,
            snapshot_id=jd_snapshot_id,
            snapshot_version=jd_snapshot_version,
        ),
    }


def _owned_active_event(db: Session, user_pk: int, event_id: str) -> ProcessEvent:
    event_row = (
        db.query(ProcessEvent)
        .join(
            JobOpportunity,
            JobOpportunity.id == ProcessEvent.job_opportunity_id,
        )
        .filter(ProcessEvent.id == event_id, JobOpportunity.user_id == user_pk)
        .one_or_none()
    )
    if event_row is None:
        raise CareerObjectNotFoundError(event_id)
    if event_row.id not in _active_event_ids(_events(db, event_row.job_opportunity_id)):
        raise ProcessEventConflictError("source ProcessEvent is inactive")
    return event_row


def _events(db: Session, opportunity_id: str) -> list[ProcessEvent]:
    return (
        db.query(ProcessEvent)
        .filter(ProcessEvent.job_opportunity_id == opportunity_id)
        .order_by(ProcessEvent.sequence.asc())
        .all()
    )


def _active_event_ids(events: list[ProcessEvent]) -> set[str]:
    # Work backwards so a future superseding correction disables the older
    # correction's effect as well as its asserted value. The Stage 2 command
    # surface currently rejects correction-of-correction, but replay remains
    # deterministic if migrated history contains one.
    active: set[str] = set()
    inactive: set[str] = set()
    for event_row in reversed(events):
        if event_row.id in inactive:
            continue
        if event_row.corrects_event_id:
            inactive.add(event_row.corrects_event_id)
        if event_row.operation == "assert":
            active.add(event_row.id)
    return active


def _event_by_idempotency(
    db: Session,
    opportunity_id: str,
    idempotency_key: str,
) -> ProcessEvent | None:
    return (
        db.query(ProcessEvent)
        .filter(
            ProcessEvent.job_opportunity_id == opportunity_id,
            ProcessEvent.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )


def _first_event(db: Session, opportunity_id: str) -> ProcessEvent | None:
    return (
        db.query(ProcessEvent)
        .filter(ProcessEvent.job_opportunity_id == opportunity_id)
        .order_by(ProcessEvent.sequence.asc())
        .first()
    )


def _find_strong_match(
    db: Session,
    *,
    user_pk: int,
    source_provider: str | None,
    external_job_id: str | None,
    external_application_id: str | None,
    normalized_url: str | None,
    skip_terminal_job_match: bool,
) -> JobOpportunity | None:
    if source_provider and external_application_id:
        query = db.query(JobOpportunity).filter(
            JobOpportunity.user_id == user_pk,
            JobOpportunity.source_provider == source_provider,
            JobOpportunity.external_application_id == external_application_id,
        )
        row = query.one_or_none()
        if row is not None:
            return row

    conditions = []
    if source_provider and external_job_id:
        conditions.append(
            (JobOpportunity.source_provider == source_provider)
            & (JobOpportunity.external_job_id == external_job_id)
        )
    if normalized_url:
        conditions.append(JobOpportunity.normalized_source_url == normalized_url)
    if not conditions:
        return None
    query = db.query(JobOpportunity).filter(
        JobOpportunity.user_id == user_pk,
        or_(*conditions),
    )
    active = (
        query.filter(JobOpportunity.outcome.is_(None))
        .order_by(JobOpportunity.created_at.desc())
        .first()
    )
    if active is not None or skip_terminal_job_match:
        return active
    # Without explicit reapplication confirmation, an exact terminal job/URL
    # resolves to history rather than silently creating a new line.
    return query.order_by(JobOpportunity.created_at.desc()).first()


def _enrich_identity(
    opportunity: JobOpportunity,
    *,
    location: str | None,
    team: str | None,
    source_url: str | None,
    normalized_url: str | None,
    source_provider: str | None,
    external_job_id: str | None,
    external_application_id: str | None,
) -> None:
    for field, value in {
        "location": _optional_text(location, 200),
        "team": _optional_text(team, 200),
        "source_url": source_url,
        "normalized_source_url": normalized_url,
        "source_provider": source_provider,
        "external_job_id": external_job_id,
        "external_application_id": external_application_id,
    }.items():
        if getattr(opportunity, field) is None and value is not None:
            setattr(opportunity, field, value)


def _same_opportunity_command(
    opportunity: JobOpportunity,
    *,
    company_name: str,
    job_title: str,
    source_provider: str | None,
    external_job_id: str | None,
    external_application_id: str | None,
    normalized_url: str | None,
) -> bool:
    return (
        opportunity.company_name == company_name
        and opportunity.job_title == job_title
        and (source_provider is None or opportunity.source_provider == source_provider)
        and (external_job_id is None or opportunity.external_job_id == external_job_id)
        and (
            external_application_id is None
            or opportunity.external_application_id == external_application_id
        )
        and (
            normalized_url is None
            or opportunity.normalized_source_url == normalized_url
        )
    )


def _same_event(
    event_row: ProcessEvent,
    *,
    operation: str,
    kind: str,
    occurred_at: datetime,
    source_kind: str,
    source_identity: str,
    source_version: str | None,
    description: str,
    step_summary: str | None,
    corrects_event_id: str | None,
    application_channel: str | None = None,
) -> bool:
    return (
        event_row.operation == operation
        and event_row.kind == kind
        and as_utc(event_row.occurred_at) == as_utc(occurred_at)
        and event_row.source_kind == source_kind
        and event_row.source_identity == source_identity.strip()
        and event_row.source_version == _optional_text(source_version, 128)
        and event_row.description == description.strip()
        and event_row.step_summary == _optional_text(step_summary, 300)
        and event_row.corrects_event_id == corrects_event_id
        and (
            application_channel is None
            or str((event_row.analysis_context_json or {}).get("channel") or "")
            == _text(application_channel, "application_channel", 160)
        )
    )


def _same_action(
    action: NextAction,
    command: NextActionCreate,
    content: str,
    opportunity_id: str | None,
) -> bool:
    return (
        action.content == content
        and action.time_kind == command.time_kind
        and action.job_opportunity_id == opportunity_id
        and action.interview_record_id == command.interview_record_id
        and action.offer_id == command.offer_id
        and action.artifact_id == command.artifact_id
        and as_utc(action.starts_at) == as_utc(command.starts_at)
        and as_utc(action.ends_at) == as_utc(command.ends_at)
        and as_utc(action.due_at) == as_utc(command.due_at)
        and action.original_time_text == _optional_text(command.original_time_text, 300)
        and action.source_timezone == _optional_text(command.source_timezone, 80)
        and action.source_kind == command.source_kind
        and action.source_identity == command.source_identity.strip()
        and action.source_version == _optional_text(command.source_version, 128)
        and as_utc(action.reminder_at) == as_utc(command.reminder_at)
        and action.reminder_channel == command.reminder_channel
    )


def _entry_event_key(command: OpportunityCreate) -> str:
    return _natural_event_key(
        command.source_kind,
        command.source_identity,
        _ENTRY_EVENT[command.entry_reason],
        None,
    )


def _natural_event_key(
    source_kind: str,
    source_identity: str,
    kind: str,
    corrects_event_id: str | None,
) -> str:
    return "source:" + _digest(
        source_kind,
        source_identity.strip(),
        kind,
        corrects_event_id or "",
    )


def _natural_action_key(source_kind: str, source_identity: str, content: str) -> str:
    return "source:" + _digest(source_kind, source_identity.strip(), content)


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise CareerProcessError("source_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise CareerProcessError("source_url must not contain credentials")
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
    # Reordering duplicate query keys can change URL semantics. Unique keys are
    # safe to sort for exact-match normalization; duplicates retain source order.
    if len(query_names) == len(set(query_names)):
        query_pairs.sort()
    query = urlencode(query_pairs)
    return urlunsplit((parsed.scheme.lower(), hostname, path, query, ""))


def _text(value: str, field: str, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise CareerProcessError(f"{field} is required")
    if len(normalized) > max_length:
        raise CareerProcessError(f"{field} exceeds {max_length} characters")
    return normalized


def _optional_text(
    value: str | None,
    max_length: int,
    *,
    lower: bool = False,
) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise CareerProcessError(f"value exceeds {max_length} characters")
    return normalized.lower() if lower else normalized


__all__ = [
    "CareerIdempotencyConflictError",
    "CareerObjectNotFoundError",
    "CareerProcessError",
    "NextActionTransitionError",
    "OpportunityAdmission",
    "OpportunityArchivedError",
    "OpportunityDirectionConflictError",
    "OpportunityMergeConflictError",
    "ProcessEventConflictError",
    "append_confirmed_process_event",
    "close_next_action",
    "complete_next_action",
    "correct_process_event",
    "create_job_opportunity",
    "create_next_action",
    "edit_next_action",
    "list_job_opportunities",
    "list_opportunity_merges",
    "list_next_actions",
    "list_process_events",
    "plan_next_action",
    "merge_job_opportunities",
    "retract_job_opportunity_merge",
    "suggest_opportunity_merge_candidates",
    "replace_job_opportunity_directions",
]
