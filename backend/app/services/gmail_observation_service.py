"""Application Service for Gmail Observation intake and fact promotion.

The connector owns deterministic cursor/deduplication and immutable source
snapshots.  Semantic proposals arrive from a bounded PersistentTask Turn, but
this service alone enforces ownership, task scope, confidence, archived-line,
idempotency, pending-card, and append-only correction invariants.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.types import as_utc, utc_now
from app.models.gmail_integration import GmailIntegrationAccount
from app.models.gmail_observation import (
    GmailObservation,
    GmailObservationReviewCard,
    GmailObservationSnapshot,
)
from app.models.job_opportunity import JobOpportunity
from app.models.persistent_task import PersistentTask, PersistentTaskTrigger
from app.schemas.gmail_observation import (
    GmailIncrementalBatch,
    GmailObservationCardResolve,
    GmailObservationNewOpportunity,
    GmailObservationProposal,
    GmailObservationRetract,
    GmailObservationReviewCardView,
    GmailObservationSnapshotView,
    GmailObservationView,
)
from app.schemas.job_opportunity import (
    OpportunityCreate,
    ProcessEventAppend,
    ProcessEventCorrection,
)
from app.services import career_process_service


AUTO_APPLY_ACTION_SCOPE = "career.process_event.auto_apply"
GMAIL_EVENT_CONNECTOR = "gmail"
GMAIL_MESSAGE_ADDED_EVENT = "message_added"
_MAIL_EVENT_KINDS = frozenset(
    {
        "application_submitted",
        "application_acknowledged",
        "recruiter_contact",
        "assessment_invited",
        "assessment_completed",
        "hiring_step",
        "interview_scheduled",
        "interview_completed",
        "background_check_started",
        "offer_received",
        "rejected",
        "posting_closed",
    }
)
_AUTO_APPLY_KINDS = frozenset(
    {
        "application_submitted",
        "application_acknowledged",
        "assessment_invited",
        "interview_scheduled",
        "offer_received",
        "rejected",
        "posting_closed",
    }
)
_AUTO_APPLY_CONFIDENCE = 0.95


class GmailObservationError(ValueError):
    """Base deterministic Observation command error."""


class GmailObservationNotFoundError(GmailObservationError):
    pass


class GmailObservationConflictError(GmailObservationError):
    pass


class GmailObservationScopeError(GmailObservationError):
    pass


@dataclass(frozen=True)
class GmailObservationIntake:
    observations: tuple[GmailObservation, ...]
    snapshots: tuple[GmailObservationSnapshot, ...]
    initialized_cursor: bool
    cursor_after: str


@dataclass(frozen=True)
class GmailObservationProposalResult:
    observation: GmailObservation
    card: GmailObservationReviewCard | None
    process_event_id: str | None
    outcome: str


def persist_incremental_batch(
    db: Session,
    *,
    user_pk: int,
    account_id: str,
    batch: GmailIncrementalBatch,
) -> GmailObservationIntake:
    """Persist a complete provider increment and advance its cursor atomically."""

    account = (
        db.query(GmailIntegrationAccount)
        .filter(
            GmailIntegrationAccount.id == account_id,
            GmailIntegrationAccount.user_id == user_pk,
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if account is None:
        raise GmailObservationNotFoundError("gmail_account_not_found")
    stored_cursor = _optional_text(account.history_cursor)
    expected_cursor = _optional_text(batch.cursor_before)
    if stored_cursor != expected_cursor:
        raise GmailObservationConflictError("gmail_history_cursor_changed")

    now = utc_now()
    observations: list[GmailObservation] = []
    snapshots: list[GmailObservationSnapshot] = []
    for message in batch.messages:
        observation = (
            db.query(GmailObservation)
            .filter(
                GmailObservation.gmail_account_id == account.id,
                GmailObservation.provider_message_id == message.message_id,
            )
            .with_for_update()
            .one_or_none()
        )
        created_observation = observation is None
        if observation is None:
            observation = GmailObservation(
                user_id=user_pk,
                gmail_account_id=account.id,
                provider_message_id=message.message_id,
                provider_thread_id=message.thread_id,
                received_at=message.received_at,
                observed_at=now,
                status="unreviewed",
                version=1,
                created_at=now,
                updated_at=now,
            )
            db.add(observation)
            db.flush()
        elif observation.user_id != user_pk:
            raise GmailObservationScopeError("gmail_observation_owner_mismatch")

        digest = _snapshot_digest(message.model_dump(mode="json"))
        snapshot_version = f"{message.history_id}:{digest[:32]}"
        existing_snapshot = (
            db.query(GmailObservationSnapshot)
            .filter(
                GmailObservationSnapshot.observation_id == observation.id,
                GmailObservationSnapshot.snapshot_version == snapshot_version,
            )
            .one_or_none()
        )
        if existing_snapshot is not None:
            continue
        snapshot = GmailObservationSnapshot(
            observation_id=observation.id,
            snapshot_version=snapshot_version,
            provider_history_id=message.history_id,
            provider_message_id=message.message_id,
            provider_thread_id=message.thread_id,
            content_available=message.content_available,
            received_at=message.received_at,
            from_hint=message.from_hint,
            subject=message.subject,
            snippet=message.snippet,
            content_sha256=digest,
            observed_at=now,
            created_at=now,
        )
        db.add(snapshot)
        db.flush()
        # A source-version change is observable but never overwrites a fact
        # already promoted from an earlier immutable snapshot.
        observation.provider_thread_id = message.thread_id
        observation.received_at = message.received_at
        observation.observed_at = now
        observation.updated_at = now
        if not created_observation and observation.status in {
            "unreviewed",
            "dismissed",
            "retracted",
        }:
            observation.status = "unreviewed"
            observation.version += 1
        db.add(observation)
        observations.append(observation)
        snapshots.append(snapshot)

    account.history_cursor = batch.cursor_after
    account.history_cursor_updated_at = now
    account.last_observation_sync_at = now
    account.last_observation_sync_error_code = None
    account.updated_at = now
    db.add(account)
    db.flush()
    return GmailObservationIntake(
        observations=tuple(observations),
        snapshots=tuple(snapshots),
        initialized_cursor=batch.initialized_cursor,
        cursor_after=batch.cursor_after,
    )


def record_sync_error(
    db: Session,
    *,
    user_pk: int,
    account_id: str,
    error_code: str,
) -> None:
    account = (
        db.query(GmailIntegrationAccount)
        .filter(
            GmailIntegrationAccount.id == account_id,
            GmailIntegrationAccount.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if account is None:
        return
    account.last_observation_sync_at = utc_now()
    account.last_observation_sync_error_code = _safe_error_code(error_code)
    account.updated_at = utc_now()
    db.add(account)
    db.flush()


def rebaseline_history_cursor(
    db: Session,
    *,
    user_pk: int,
    account_id: str,
) -> None:
    """Explicitly acknowledge an expired cursor and initialize from now.

    Existing Observation snapshots remain immutable.  The next sync reads the
    provider profile cursor and records no fabricated messages for the unknown
    interval.
    """

    account = (
        db.query(GmailIntegrationAccount)
        .filter(
            GmailIntegrationAccount.id == account_id,
            GmailIntegrationAccount.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if account is None:
        raise GmailObservationNotFoundError("gmail_account_not_found")
    account.history_cursor = None
    account.history_cursor_updated_at = None
    account.last_observation_sync_error_code = None
    account.updated_at = utc_now()
    db.add(account)
    db.flush()


def list_observations(
    db: Session,
    *,
    user_pk: int,
    statuses: set[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    query = db.query(GmailObservation).filter(GmailObservation.user_id == user_pk)
    if statuses:
        query = query.filter(GmailObservation.status.in_(statuses))
    rows = (
        query.order_by(GmailObservation.observed_at.desc(), GmailObservation.id.desc())
        .limit(max(1, min(int(limit), 200)))
        .all()
    )
    return [_observation_view(db, row) for row in rows]


def get_observation(
    db: Session,
    *,
    user_pk: int,
    observation_id: str,
) -> dict:
    return _observation_view(db, _owned_observation(db, user_pk, observation_id))


def list_review_cards(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    statuses: set[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    _owned_task(db, user_pk, task_id)
    query = db.query(GmailObservationReviewCard).filter(
        GmailObservationReviewCard.persistent_task_id == task_id
    )
    if statuses:
        query = query.filter(GmailObservationReviewCard.status.in_(statuses))
    cards = (
        query.order_by(
            GmailObservationReviewCard.created_at.asc(),
            GmailObservationReviewCard.id.asc(),
        )
        .limit(max(1, min(int(limit), 200)))
        .all()
    )
    return [_card_view(db, card) for card in cards]


def get_review_card(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    card_id: str,
) -> dict:
    _owned_task(db, user_pk, task_id)
    card = (
        db.query(GmailObservationReviewCard)
        .filter(
            GmailObservationReviewCard.id == card_id,
            GmailObservationReviewCard.persistent_task_id == task_id,
        )
        .one_or_none()
    )
    if card is None:
        raise GmailObservationNotFoundError("review_card_not_found")
    return _card_view(db, card)


def propose_observation(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    automation_turn_id: str,
    proposal: GmailObservationProposal,
) -> GmailObservationProposalResult:
    """Apply a bounded Turn's semantic result or create a review card."""

    task = _owned_task(db, user_pk, task_id, lock=True)
    _require_gmail_event_task(task)
    observation = _owned_observation(db, user_pk, proposal.observation_id, lock=True)
    _require_triggered_observation(
        db,
        task_id=task.id,
        observation_id=observation.id,
        automation_turn_id=automation_turn_id,
    )
    _require_version(observation.version, proposal.expected_version)
    if observation.status == "applied":
        return GmailObservationProposalResult(
            observation=observation,
            card=None,
            process_event_id=observation.applied_process_event_id,
            outcome="already_applied",
        )

    if proposal.disposition == "dismiss":
        observation.status = "dismissed"
        observation.analysis_summary = proposal.rationale
        observation.classification_confidence = proposal.confidence
        observation.unique_match = proposal.unique_match
        observation.version += 1
        observation.updated_at = utc_now()
        db.add(observation)
        db.flush()
        return GmailObservationProposalResult(
            observation=observation,
            card=None,
            process_event_id=None,
            outcome="dismissed",
        )

    _validate_mail_event_kind(str(proposal.event_kind))
    snapshot = _latest_snapshot(db, observation.id)
    observation.candidate_event_kind = proposal.event_kind
    observation.classification_confidence = proposal.confidence
    observation.unique_match = proposal.unique_match
    observation.analysis_summary = proposal.rationale

    auto_allowed = _can_auto_apply(db, task, proposal)
    if proposal.disposition == "auto_apply" and auto_allowed:
        event = _apply_candidate(
            db,
            user_pk=user_pk,
            observation=observation,
            snapshot=snapshot,
            event_kind=str(proposal.event_kind),
            opportunity_id=proposal.opportunity_id,
            new_opportunity=proposal.new_opportunity,
            occurred_at=proposal.occurred_at,
            description=str(proposal.description),
            step_summary=proposal.step_summary,
        )
        _mark_applied(observation, event.id, proposal.rationale)
        db.flush()
        return GmailObservationProposalResult(
            observation=observation,
            card=None,
            process_event_id=event.id,
            outcome="applied",
        )

    card = _create_review_card(
        db,
        task=task,
        observation=observation,
        snapshot=snapshot,
        proposal=proposal,
    )
    observation.status = "pending_confirmation"
    observation.version += 1
    observation.updated_at = utc_now()
    db.add(observation)
    db.flush()
    return GmailObservationProposalResult(
        observation=observation,
        card=card,
        process_event_id=None,
        outcome="pending_confirmation",
    )


def resolve_review_card(
    db: Session,
    *,
    user_pk: int,
    task_id: str,
    card_id: str,
    command: GmailObservationCardResolve,
) -> GmailObservationProposalResult:
    task = _owned_task(db, user_pk, task_id, lock=True)
    card = (
        db.query(GmailObservationReviewCard)
        .filter(
            GmailObservationReviewCard.id == card_id,
            GmailObservationReviewCard.persistent_task_id == task.id,
        )
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if card is None:
        raise GmailObservationNotFoundError("review_card_not_found")
    _require_version(card.version, command.expected_version)
    if card.status != "pending":
        raise GmailObservationConflictError("review_card_already_resolved")
    observation = _owned_observation(db, user_pk, card.observation_id, lock=True)
    snapshot = _snapshot(db, observation.id, card.source_snapshot_id)
    now = utc_now()
    if command.decision != "approve":
        card.status = "rejected" if command.decision == "reject" else "skipped"
        card.resolution_note = command.resolution_note
        card.user_request_identity = command.user_request_identity
        card.user_request_version = _optional_text(command.user_request_version)
        card.resolved_at = now
        card.version += 1
        card.updated_at = now
        observation.status = "dismissed"
        observation.notification_summary = (
            "用户已拒绝此候选变更。"
            if command.decision == "reject"
            else "用户已跳过此候选变更。"
        )
        observation.version += 1
        observation.updated_at = now
        db.add_all([card, observation])
        db.flush()
        return GmailObservationProposalResult(
            observation=observation,
            card=card,
            process_event_id=None,
            outcome=card.status,
        )

    event_kind = str(command.event_kind or card.candidate_event_kind)
    _validate_mail_event_kind(event_kind)
    opportunity_id = command.opportunity_id or card.candidate_opportunity_id
    new_opportunity = command.new_opportunity or (
        GmailObservationNewOpportunity.model_validate(card.new_opportunity_json)
        if card.new_opportunity_json
        else None
    )
    if command.opportunity_id is not None:
        new_opportunity = None
    if command.new_opportunity is not None:
        opportunity_id = None
    event = _apply_candidate(
        db,
        user_pk=user_pk,
        observation=observation,
        snapshot=snapshot,
        event_kind=event_kind,
        opportunity_id=opportunity_id,
        new_opportunity=new_opportunity,
        occurred_at=command.occurred_at or card.occurred_at,
        description=command.description or card.description,
        step_summary=(
            command.step_summary
            if command.step_summary is not None
            else card.step_summary
        ),
    )
    card.status = "approved"
    card.process_event_id = event.id
    card.resolution_note = command.resolution_note
    card.user_request_identity = command.user_request_identity
    card.user_request_version = _optional_text(command.user_request_version)
    card.resolved_at = now
    card.version += 1
    card.updated_at = now
    _mark_applied(observation, event.id, command.resolution_note or card.rationale)
    db.add_all([card, observation])
    db.flush()
    return GmailObservationProposalResult(
        observation=observation,
        card=card,
        process_event_id=event.id,
        outcome="applied",
    )


def retract_applied_observation(
    db: Session,
    *,
    user_pk: int,
    observation_id: str,
    command: GmailObservationRetract,
):
    observation = _owned_observation(db, user_pk, observation_id, lock=True)
    _require_version(observation.version, command.expected_version)
    if observation.status != "applied" or not observation.applied_process_event_id:
        raise GmailObservationConflictError("observation_has_no_active_application")
    if not observation.matched_job_opportunity_id:
        raise GmailObservationConflictError("applied_opportunity_unavailable")
    correction = career_process_service.correct_process_event(
        db,
        user_pk=user_pk,
        opportunity_id=observation.matched_job_opportunity_id,
        target_event_id=observation.applied_process_event_id,
        command=ProcessEventCorrection(
            occurred_at=command.occurred_at,
            observed_at=utc_now(),
            source_kind="user_assertion",
            source_identity=command.user_request_identity,
            source_version=command.user_request_version,
            description=command.reason,
            idempotency_key=(
                f"gmail-observation:{observation.id}:retract:v{observation.version}"
            ),
        ),
    )
    observation.status = "retracted"
    observation.retraction_process_event_id = correction.id
    observation.notification_summary = "已按用户要求撤销此前自动记录的流程事件。"
    observation.version += 1
    observation.updated_at = utc_now()
    db.add(observation)
    db.flush()
    return correction


def _can_auto_apply(
    db: Session,
    task: PersistentTask,
    proposal: GmailObservationProposal,
) -> bool:
    if (
        proposal.event_kind not in _AUTO_APPLY_KINDS
        or proposal.confidence < _AUTO_APPLY_CONFIDENCE
        or not proposal.unique_match
        or AUTO_APPLY_ACTION_SCOPE not in set(task.action_scope_json or [])
    ):
        return False
    # Creating a new opportunity makes its submission the sole admission fact;
    # the career domain deliberately forbids retracting that only fact.  Keep
    # all new-opportunity and duplicate-submission candidates reviewable so an
    # automatic change always retains the promised append-only correction path.
    if (
        proposal.new_opportunity is not None
        or proposal.event_kind == "application_submitted"
    ):
        return False
    opportunity = (
        db.query(JobOpportunity)
        .filter(
            JobOpportunity.id == proposal.opportunity_id,
            JobOpportunity.user_id == task.user_id,
        )
        .one_or_none()
    )
    if opportunity is None or opportunity.outcome is not None:
        return False
    if (
        opportunity.last_event_at is not None
        and proposal.occurred_at is not None
        and as_utc(proposal.occurred_at) < as_utc(opportunity.last_event_at)
    ):
        return False
    return True


def _apply_candidate(
    db: Session,
    *,
    user_pk: int,
    observation: GmailObservation,
    snapshot: GmailObservationSnapshot,
    event_kind: str,
    opportunity_id: str | None,
    new_opportunity: GmailObservationNewOpportunity | None,
    occurred_at,
    description: str,
    step_summary: str | None,
):
    if occurred_at is None:
        raise GmailObservationConflictError("candidate_occurred_at_required")
    if new_opportunity is not None:
        if event_kind != "application_submitted":
            raise GmailObservationConflictError(
                "only a verified submission may create an opportunity"
            )
        admission = career_process_service.create_job_opportunity(
            db,
            user_pk=user_pk,
            command=OpportunityCreate(
                company_name=new_opportunity.company_name,
                job_title=new_opportunity.job_title,
                entry_reason="verified_submission",
                occurred_at=occurred_at,
                source_kind="observation",
                source_identity=snapshot.id,
                source_version=snapshot.snapshot_version,
                source_description=description,
                location=new_opportunity.location,
                source_url=new_opportunity.source_url,
                source_provider=new_opportunity.application_provider,
                external_job_id=new_opportunity.external_job_id,
                external_application_id=new_opportunity.external_application_id,
                idempotency_key=(f"gmail-observation:{observation.id}:opportunity"),
            ),
        )
        if admission.initial_event is None:
            raise GmailObservationConflictError("verified_submission_event_missing")
        observation.matched_job_opportunity_id = admission.opportunity.id
        return admission.initial_event
    if opportunity_id is None:
        raise GmailObservationConflictError("candidate_opportunity_required")
    event = career_process_service.append_confirmed_process_event(
        db,
        user_pk=user_pk,
        opportunity_id=opportunity_id,
        command=ProcessEventAppend(
            kind=event_kind,
            occurred_at=occurred_at,
            observed_at=utc_now(),
            source_kind="observation",
            source_identity=snapshot.id,
            source_version=snapshot.snapshot_version,
            description=description,
            step_summary=step_summary,
            idempotency_key=(
                f"gmail-observation:{observation.id}:event:{event_kind}:"
                f"{snapshot.snapshot_version}"
            ),
        ),
    )
    observation.matched_job_opportunity_id = opportunity_id
    return event


def _mark_applied(
    observation: GmailObservation,
    process_event_id: str,
    rationale: str,
) -> None:
    observation.status = "applied"
    observation.applied_process_event_id = process_event_id
    observation.retraction_process_event_id = None
    observation.notification_summary = (
        "已根据唯一匹配且语义明确的 Gmail Observation 自动记录流程事件；"
        "可在此撤销或修正。"
    )
    observation.analysis_summary = rationale
    observation.version += 1
    observation.updated_at = utc_now()


def _create_review_card(
    db: Session,
    *,
    task: PersistentTask,
    observation: GmailObservation,
    snapshot: GmailObservationSnapshot,
    proposal: GmailObservationProposal,
) -> GmailObservationReviewCard:
    existing = (
        db.query(GmailObservationReviewCard)
        .filter(
            GmailObservationReviewCard.persistent_task_id == task.id,
            GmailObservationReviewCard.observation_id == observation.id,
        )
        .with_for_update()
        .one_or_none()
    )
    expected = {
        "source_snapshot_id": snapshot.id,
        "candidate_event_kind": str(proposal.event_kind),
        "candidate_opportunity_id": proposal.opportunity_id,
        "occurred_at": proposal.occurred_at,
        "description": str(proposal.description),
        "step_summary": proposal.step_summary,
        "new_opportunity_json": (
            proposal.new_opportunity.model_dump(mode="json")
            if proposal.new_opportunity is not None
            else None
        ),
    }
    if existing is not None:
        if existing.status != "pending" or any(
            getattr(existing, field) != value for field, value in expected.items()
        ):
            raise GmailObservationConflictError(
                "observation already has a different task review card"
            )
        return existing
    card = GmailObservationReviewCard(
        persistent_task_id=task.id,
        observation_id=observation.id,
        source_snapshot_id=snapshot.id,
        status="pending",
        version=1,
        candidate_event_kind=str(proposal.event_kind),
        candidate_opportunity_id=proposal.opportunity_id,
        occurred_at=proposal.occurred_at,
        description=str(proposal.description),
        step_summary=proposal.step_summary,
        confidence=proposal.confidence,
        unique_match=proposal.unique_match,
        rationale=proposal.rationale,
        new_opportunity_json=expected["new_opportunity_json"],
    )
    db.add(card)
    db.flush()
    return card


def _require_triggered_observation(
    db: Session,
    *,
    task_id: str,
    observation_id: str,
    automation_turn_id: str,
) -> None:
    trigger = (
        db.query(PersistentTaskTrigger.id)
        .filter(
            PersistentTaskTrigger.persistent_task_id == task_id,
            PersistentTaskTrigger.kind == "event",
            PersistentTaskTrigger.source_identity == observation_id,
            PersistentTaskTrigger.admitted_turn_id == automation_turn_id,
        )
        .first()
    )
    if trigger is None:
        raise GmailObservationScopeError(
            "observation was not admitted into this automation Turn"
        )


def _require_gmail_event_task(task: PersistentTask) -> None:
    spec = dict(task.trigger_spec_json or {})
    if (
        task.trigger_kind != "event"
        or spec.get("connector") != GMAIL_EVENT_CONNECTOR
        or GMAIL_MESSAGE_ADDED_EVENT not in set(spec.get("event_types") or [])
        or "gmail:job_observations" not in set(task.read_scope_json or [])
        or not {
            "read_career_context",
            "read_gmail_observations",
            "review_gmail_observation",
        }.issubset(set(task.allowed_tool_names_json or []))
    ):
        raise GmailObservationScopeError("task is not a Gmail event observer")


def _validate_mail_event_kind(event_kind: str) -> None:
    if event_kind not in _MAIL_EVENT_KINDS:
        raise GmailObservationConflictError(
            "Gmail Observation cannot assert this ProcessEvent kind"
        )


def _owned_task(
    db: Session,
    user_pk: int,
    task_id: str,
    *,
    lock: bool = False,
) -> PersistentTask:
    query = db.query(PersistentTask).filter(
        PersistentTask.id == task_id, PersistentTask.user_id == user_pk
    )
    if lock:
        query = query.with_for_update().populate_existing()
    task = query.one_or_none()
    if task is None:
        raise GmailObservationNotFoundError("persistent_task_not_found")
    return task


def _owned_observation(
    db: Session,
    user_pk: int,
    observation_id: str,
    *,
    lock: bool = False,
) -> GmailObservation:
    query = db.query(GmailObservation).filter(
        GmailObservation.id == observation_id,
        GmailObservation.user_id == user_pk,
    )
    if lock:
        query = query.with_for_update().populate_existing()
    observation = query.one_or_none()
    if observation is None:
        raise GmailObservationNotFoundError("gmail_observation_not_found")
    return observation


def _latest_snapshot(db: Session, observation_id: str) -> GmailObservationSnapshot:
    snapshot = (
        db.query(GmailObservationSnapshot)
        .filter(GmailObservationSnapshot.observation_id == observation_id)
        .order_by(
            GmailObservationSnapshot.observed_at.desc(),
            GmailObservationSnapshot.id.desc(),
        )
        .first()
    )
    if snapshot is None:
        raise GmailObservationNotFoundError("gmail_observation_snapshot_not_found")
    return snapshot


def _snapshot(
    db: Session,
    observation_id: str,
    snapshot_id: str,
) -> GmailObservationSnapshot:
    snapshot = (
        db.query(GmailObservationSnapshot)
        .filter(
            GmailObservationSnapshot.id == snapshot_id,
            GmailObservationSnapshot.observation_id == observation_id,
        )
        .one_or_none()
    )
    if snapshot is None:
        raise GmailObservationNotFoundError("gmail_observation_snapshot_not_found")
    return snapshot


def _observation_view(db: Session, observation: GmailObservation) -> dict:
    payload = GmailObservationView.model_validate(
        {
            **{
                field: getattr(observation, field)
                for field in GmailObservationView.model_fields
                if field != "latest_snapshot"
            },
            "latest_snapshot": GmailObservationSnapshotView.model_validate(
                _latest_snapshot(db, observation.id)
            ),
        }
    )
    return payload.model_dump(mode="json")


def _card_view(db: Session, card: GmailObservationReviewCard) -> dict:
    payload = GmailObservationReviewCardView.model_validate(
        {
            **{
                field: getattr(card, field)
                for field in GmailObservationReviewCardView.model_fields
                if field != "source_snapshot"
            },
            "source_snapshot": GmailObservationSnapshotView.model_validate(
                _snapshot(db, card.observation_id, card.source_snapshot_id)
            ),
        }
    )
    return payload.model_dump(mode="json")


def _snapshot_digest(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_version(actual: int, expected: int) -> None:
    if int(actual) != int(expected):
        raise GmailObservationConflictError(
            f"expected version {expected}, found {actual}"
        )


def _optional_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _safe_error_code(value: str) -> str:
    normalized = "".join(
        character
        for character in (value or "").strip().lower()
        if character.isascii() and (character.isalnum() or character == "_")
    )
    return normalized[:64] or "provider_error"


__all__ = [
    "AUTO_APPLY_ACTION_SCOPE",
    "GMAIL_EVENT_CONNECTOR",
    "GMAIL_MESSAGE_ADDED_EVENT",
    "GmailObservationConflictError",
    "GmailObservationError",
    "GmailObservationIntake",
    "GmailObservationNotFoundError",
    "GmailObservationProposalResult",
    "GmailObservationScopeError",
    "get_observation",
    "get_review_card",
    "list_observations",
    "list_review_cards",
    "persist_incremental_batch",
    "propose_observation",
    "rebaseline_history_cursor",
    "record_sync_error",
    "resolve_review_card",
    "retract_applied_observation",
]
