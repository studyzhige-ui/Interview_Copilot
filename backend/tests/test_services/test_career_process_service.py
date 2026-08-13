from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.career_profile import CareerProfile, CareerProfileDirection
from app.models.job_opportunity import (
    JobOpportunity,
    JobOpportunityMerge,
    NextAction,
    ProcessEvent,
    ProcessEventImmutableError,
)
from app.models.user import User
from app.schemas.job_opportunity import (
    NextActionClose,
    NextActionCreate,
    NextActionTransition,
    OpportunityCreate,
    OpportunityDirectionsReplace,
    OpportunityMergeCreate,
    OpportunityMergeRetract,
    ProcessEventAppend,
    ProcessEventCorrection,
)
from app.services.career_process_service import (
    CareerIdempotencyConflictError,
    CareerObjectNotFoundError,
    NextActionTransitionError,
    OpportunityArchivedError,
    OpportunityDirectionConflictError,
    OpportunityMergeConflictError,
    ProcessEventConflictError,
    append_confirmed_process_event,
    close_next_action,
    complete_next_action,
    correct_process_event,
    create_job_opportunity,
    create_next_action,
    list_job_opportunities,
    list_opportunity_merges,
    list_next_actions,
    list_process_events,
    plan_next_action,
    merge_job_opportunities,
    retract_job_opportunity_merge,
    replace_job_opportunity_directions,
    suggest_opportunity_merge_candidates,
)


NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)


def _user(db_session, username: str = "career-owner") -> User:
    user = User(username=username, hashed_password="x")
    db_session.add(user)
    db_session.flush()
    return user


def _direction(db_session, user: User, label: str) -> CareerProfileDirection:
    profile = (
        db_session.query(CareerProfile)
        .filter(CareerProfile.user_id == user.id)
        .one_or_none()
    )
    if profile is None:
        profile = CareerProfile(user_id=user.id, personal_facts_json=[])
        db_session.add(profile)
        db_session.flush()
    direction = CareerProfileDirection(
        career_profile_id=profile.id,
        label=label,
        criteria_json={},
        lifecycle="active",
        priority=0,
        confirmed_source_kind="user_edit",
        confirmed_at=NOW,
    )
    db_session.add(direction)
    db_session.flush()
    return direction


def _opportunity_command(
    *,
    reason: str = "explicit_tracking",
    source_identity: str = "message-1",
    source_url: str | None = "HTTPS://Jobs.Example.com/roles/42/?b=2&a=1#details",
    idempotency_key: str | None = "create-1",
    **overrides,
) -> OpportunityCreate:
    values = {
        "company_name": "Example Corp",
        "job_title": "Backend Engineer",
        "entry_reason": reason,
        "occurred_at": NOW,
        "source_kind": "user_assertion",
        "source_identity": source_identity,
        "source_description": "用户明确要求跟踪这个岗位",
        "source_url": source_url,
        "source_provider": "example",
        "external_job_id": "job-42",
        "idempotency_key": idempotency_key,
    }
    values.update(overrides)
    return OpportunityCreate(**values)


def _create(db_session, user: User, **overrides):
    return create_job_opportunity(
        db_session,
        user_pk=user.id,
        command=_opportunity_command(**overrides),
    )


def _append(db_session, user: User, opportunity_id: str, kind: str, **overrides):
    values = {
        "kind": kind,
        "occurred_at": NOW + timedelta(days=1),
        "source_kind": "user_assertion",
        "source_identity": f"message-{kind}",
        "description": f"confirmed {kind}",
    }
    values.update(overrides)
    return append_confirmed_process_event(
        db_session,
        user_pk=user.id,
        opportunity_id=opportunity_id,
        command=ProcessEventAppend(**values),
    )


def test_create_opportunity_writes_first_confirmed_fact_and_projection(db_session):
    user = _user(db_session)

    admitted = _create(db_session, user)

    assert admitted.created is True
    assert admitted.opportunity.phase == "pending_application"
    assert admitted.opportunity.outcome is None
    assert admitted.opportunity.current_step == "已加入跟踪"
    assert admitted.opportunity.normalized_source_url == (
        "https://jobs.example.com/roles/42?a=1&b=2"
    )
    assert admitted.initial_event is not None
    assert admitted.initial_event.sequence == 1
    assert admitted.initial_event.kind == "tracking_started"
    assert admitted.initial_event.source_identity == "message-1"


def test_opportunity_merge_is_explicit_reversible_and_preserves_both_histories(
    db_session,
):
    user = _user(db_session)
    canonical = _create(db_session, user).opportunity
    duplicate = _create(
        db_session,
        user,
        source_url="https://other.example.com/jobs/99",
        external_job_id="job-99",
        idempotency_key="create-duplicate",
    ).opportunity
    before_events = {
        canonical.id: [
            row.id
            for row in list_process_events(
                db_session, user_pk=user.id, opportunity_id=canonical.id
            )
        ],
        duplicate.id: [
            row.id
            for row in list_process_events(
                db_session, user_pk=user.id, opportunity_id=duplicate.id
            )
        ],
    }

    candidates = suggest_opportunity_merge_candidates(db_session, user_pk=user.id)
    assert candidates == [
        {
            "duplicate_opportunity_id": duplicate.id,
            "canonical_opportunity_id": canonical.id,
            "reasons": ["same_company_title_location"],
        }
    ]

    merged = merge_job_opportunities(
        db_session,
        user_pk=user.id,
        command=OpportunityMergeCreate(
            duplicate_opportunity_id=duplicate.id,
            canonical_opportunity_id=canonical.id,
            operation_key="merge-explicit-1",
            reason="用户核对双方来源后确认是同一招聘流程",
        ),
    )
    assert merged.status == "active"
    assert (
        merge_job_opportunities(
            db_session,
            user_pk=user.id,
            command=OpportunityMergeCreate(
                duplicate_opportunity_id=duplicate.id,
                canonical_opportunity_id=canonical.id,
                operation_key="merge-explicit-1",
                reason="用户核对双方来源后确认是同一招聘流程",
            ),
        ).id
        == merged.id
    )
    assert list_opportunity_merges(db_session, user_pk=user.id) == [merged]

    with pytest.raises(OpportunityMergeConflictError):
        merge_job_opportunities(
            db_session,
            user_pk=user.id,
            command=OpportunityMergeCreate(
                duplicate_opportunity_id=canonical.id,
                canonical_opportunity_id=duplicate.id,
                operation_key="merge-cycle",
                reason="不允许创建合并链",
            ),
        )

    retracted = retract_job_opportunity_merge(
        db_session,
        user_pk=user.id,
        merge_id=merged.id,
        command=OpportunityMergeRetract(
            expected_version=1,
            operation_key="undo-merge-1",
            reason="用户确认它们属于不同招聘批次",
        ),
    )
    assert retracted.status == "retracted"
    assert retracted.version == 2
    assert list_opportunity_merges(db_session, user_pk=user.id) == []
    assert db_session.get(JobOpportunity, canonical.id) is canonical
    assert db_session.get(JobOpportunity, duplicate.id) is duplicate
    assert {
        canonical.id: [
            row.id
            for row in list_process_events(
                db_session, user_pk=user.id, opportunity_id=canonical.id
            )
        ],
        duplicate.id: [
            row.id
            for row in list_process_events(
                db_session, user_pk=user.id, opportunity_id=duplicate.id
            )
        ],
    } == before_events
    assert db_session.query(JobOpportunityMerge).count() == 1


def test_opportunity_direction_links_use_profile_owner_cas_and_not_event_history(
    db_session,
):
    user = _user(db_session)
    other = _user(db_session, "career-other")
    backend = _direction(db_session, user, "Backend")
    platform = _direction(db_session, user, "Platform")
    foreign = _direction(db_session, other, "Other owner")

    admitted = _create(
        db_session,
        user,
        directions=[
            {"direction_id": backend.id, "match_reason": "后端职责匹配"},
            {"direction_id": platform.id, "match_reason": "平台工程匹配"},
        ],
    )

    assert admitted.opportunity.direction_version == 1
    assert [
        link.career_profile_direction_id
        for link in admitted.opportunity.direction_links
    ] == [backend.id, platform.id]
    retried = _create(
        db_session,
        user,
        directions=[
            {"direction_id": backend.id, "match_reason": "后端职责匹配"},
            {"direction_id": platform.id, "match_reason": "平台工程匹配"},
        ],
    )
    assert retried.created is False
    assert retried.opportunity.direction_version == 1
    assert (
        len(
            list_process_events(
                db_session,
                user_pk=user.id,
                opportunity_id=admitted.opportunity.id,
            )
        )
        == 1
    )

    updated = replace_job_opportunity_directions(
        db_session,
        user_pk=user.id,
        opportunity_id=admitted.opportunity.id,
        command=OpportunityDirectionsReplace(
            expected_version=1,
            directions=[
                {"direction_id": platform.id, "match_reason": "用户调整为平台方向"},
            ],
            source_kind="user_assertion",
            source_identity="message-direction-update",
        ),
    )
    assert updated.direction_version == 2
    assert updated.direction_links[0].career_profile_direction_id == platform.id
    assert updated.direction_links[0].source_identity == "message-direction-update"
    assert (
        len(
            list_process_events(
                db_session,
                user_pk=user.id,
                opportunity_id=admitted.opportunity.id,
            )
        )
        == 1
    )

    with pytest.raises(OpportunityDirectionConflictError):
        replace_job_opportunity_directions(
            db_session,
            user_pk=user.id,
            opportunity_id=admitted.opportunity.id,
            command=OpportunityDirectionsReplace(
                expected_version=1,
                directions=[],
                source_kind="user_assertion",
                source_identity="stale-command",
            ),
        )
    with pytest.raises(CareerObjectNotFoundError):
        replace_job_opportunity_directions(
            db_session,
            user_pk=user.id,
            opportunity_id=admitted.opportunity.id,
            command=OpportunityDirectionsReplace(
                expected_version=2,
                directions=[
                    {"direction_id": foreign.id, "match_reason": "cross owner"},
                ],
                source_kind="user_assertion",
                source_identity="foreign-command",
            ),
        )


def test_exact_active_job_match_reuses_line_and_appends_submission(db_session):
    user = _user(db_session)
    first = _create(db_session, user)

    second = _create(
        db_session,
        user,
        reason="verified_submission",
        source_identity="receipt-application-42",
        idempotency_key="create-2",
        external_application_id="application-42",
        source_kind="provider_receipt",
        source_description="provider returned a successful application receipt",
    )

    assert second.created is False
    assert second.opportunity.id == first.opportunity.id
    assert second.opportunity.phase == "applied"
    assert second.opportunity.external_application_id == "application-42"
    assert [
        event.kind
        for event in list_process_events(
            db_session, user_pk=user.id, opportunity_id=first.opportunity.id
        )
    ] == ["tracking_started", "application_submitted"]


def test_terminal_line_requires_explicit_reapplication_for_same_job(db_session):
    user = _user(db_session)
    first = _create(
        db_session,
        user,
        reason="user_confirmed_application",
        source_identity="message-applied",
    )
    _append(db_session, user, first.opportunity.id, "rejected")

    implicit = _create(
        db_session,
        user,
        source_identity="message-track-again",
        idempotency_key="create-implicit",
    )
    explicit = _create(
        db_session,
        user,
        source_identity="message-reapply",
        idempotency_key="create-explicit",
        reapplication_confirmed=True,
    )

    assert implicit.created is False
    assert implicit.opportunity.id == first.opportunity.id
    assert explicit.created is True
    assert explicit.opportunity.id != first.opportunity.id


def test_projection_replays_phase_outcome_and_closes_linked_actions(db_session):
    user = _user(db_session)
    admitted = _create(
        db_session,
        user,
        reason="user_confirmed_application",
        source_identity="message-applied",
    )
    assessment = _append(
        db_session,
        user,
        admitted.opportunity.id,
        "assessment_invited",
        step_summary="技术测评周五截止",
    )
    action = create_next_action(
        db_session,
        user_pk=user.id,
        command=NextActionCreate(
            content="完成技术测评",
            status="suggested",
            time_kind="deadline",
            due_at=NOW + timedelta(days=5),
            original_time_text="本周五 18:00 前",
            source_timezone="Asia/Shanghai",
            source_kind="process_event",
            source_identity=assessment.id,
        ),
    )

    _append(db_session, user, admitted.opportunity.id, "offer_received")
    terminal = _append(
        db_session,
        user,
        admitted.opportunity.id,
        "offer_accepted",
    )

    assert admitted.opportunity.phase == "offer"
    assert admitted.opportunity.outcome == "accepted"
    assert admitted.opportunity.current_step == "已接受 Offer"
    assert admitted.opportunity.archived_at is not None
    assert action.status == "closed"
    assert action.close_reason == "job_terminal:accepted"
    assert action.resolution_source_kind == "process_event"
    assert action.resolution_source_identity == terminal.id
    with pytest.raises(OpportunityArchivedError):
        _append(db_session, user, admitted.opportunity.id, "interview_completed")


def test_correction_retracts_terminal_fact_without_rewriting_history(db_session):
    user = _user(db_session)
    admitted = _create(
        db_session,
        user,
        reason="user_confirmed_application",
        source_identity="message-applied",
    )
    rejected = _append(db_session, user, admitted.opportunity.id, "rejected")

    correction = correct_process_event(
        db_session,
        user_pk=user.id,
        opportunity_id=admitted.opportunity.id,
        target_event_id=rejected.id,
        command=ProcessEventCorrection(
            occurred_at=NOW + timedelta(days=2),
            source_kind="user_assertion",
            source_identity="message-correction",
            description="用户确认先前把另一家公司的拒信关联错了",
        ),
    )

    assert correction.operation == "retract"
    assert correction.corrects_event_id == rejected.id
    assert rejected.kind == "rejected"
    assert admitted.opportunity.outcome is None
    assert admitted.opportunity.phase == "applied"
    assert admitted.opportunity.current_step == "已确认投递"
    assert [
        row.sequence
        for row in list_process_events(
            db_session, user_pk=user.id, opportunity_id=admitted.opportunity.id
        )
    ] == [1, 2, 3]


def test_replacement_can_roll_projection_back_to_correct_fact(db_session):
    user = _user(db_session)
    admitted = _create(
        db_session,
        user,
        reason="user_confirmed_application",
        source_identity="message-applied",
    )
    interview = _append(
        db_session,
        user,
        admitted.opportunity.id,
        "interview_scheduled",
        step_summary="已约一面",
    )

    replacement = correct_process_event(
        db_session,
        user_pk=user.id,
        opportunity_id=admitted.opportunity.id,
        target_event_id=interview.id,
        command=ProcessEventCorrection(
            replacement_kind="application_acknowledged",
            occurred_at=NOW + timedelta(days=1),
            source_kind="user_assertion",
            source_identity="message-not-interview",
            description="用户澄清那只是简历收件确认",
        ),
    )

    assert replacement.operation == "assert"
    assert admitted.opportunity.phase == "applied"
    assert admitted.opportunity.current_step == "招聘方已收到申请"


def test_application_correction_preserves_original_analysis_context(db_session):
    user = _user(db_session)
    direction = _direction(db_session, user, "Backend")
    admitted = _create(
        db_session,
        user,
        reason="user_confirmed_application",
        directions=[{"direction_id": direction.id, "match_reason": "后端职责匹配"}],
    )
    assert admitted.initial_event is not None
    original_context = dict(admitted.initial_event.analysis_context_json)
    assert original_context["directions"] == [{"id": direction.id, "label": "Backend"}]

    # The canonical profile may legitimately evolve later.  Correcting the
    # historical application fact must not back-label that sample with the new
    # profile wording/version.
    direction.label = "Platform"
    profile = db_session.get(CareerProfile, direction.career_profile_id)
    assert profile is not None
    profile.version += 1
    db_session.flush()

    replacement = correct_process_event(
        db_session,
        user_pk=user.id,
        opportunity_id=admitted.opportunity.id,
        target_event_id=admitted.initial_event.id,
        command=ProcessEventCorrection(
            replacement_kind="application_submitted",
            occurred_at=NOW,
            source_kind="user_assertion",
            source_identity="message-corrected-application",
            description="用户修正了投递事实的来源说明",
            application_channel="employee_referral",
        ),
    )

    assert {
        key: value
        for key, value in replacement.analysis_context_json.items()
        if key != "channel"
    } == {key: value for key, value in original_context.items() if key != "channel"}
    assert replacement.analysis_context_json["directions"] == [
        {"id": direction.id, "label": "Backend"}
    ]
    assert replacement.analysis_context_json["channel"] == "employee_referral"


def test_process_events_reject_update_delete_and_inactive_recorrection(db_session):
    user = _user(db_session)
    admitted = _create(db_session, user)
    assessment = _append(
        db_session,
        user,
        admitted.opportunity.id,
        "assessment_invited",
    )

    with pytest.raises(NextActionTransitionError):
        create_next_action(
            db_session,
            user_pk=user.id,
            command=NextActionCreate(
                content="直接计划测评",
                status="planned",
                time_kind="deadline",
                due_at=NOW + timedelta(days=5),
                original_time_text="8 月 18 日前",
                source_timezone="Asia/Shanghai",
                source_kind="process_event",
                source_identity=assessment.id,
            ),
        )
    correct_process_event(
        db_session,
        user_pk=user.id,
        opportunity_id=admitted.opportunity.id,
        target_event_id=assessment.id,
        command=ProcessEventCorrection(
            replacement_kind="recruiter_contact",
            occurred_at=NOW + timedelta(days=2),
            source_kind="user_assertion",
            source_identity="message-fix",
            description="实际是招聘方电话沟通",
        ),
    )
    db_session.commit()

    assessment.description = "mutated"
    with pytest.raises(ProcessEventImmutableError):
        db_session.flush()
    db_session.rollback()

    persisted = db_session.get(ProcessEvent, assessment.id)
    db_session.delete(persisted)
    with pytest.raises(ProcessEventImmutableError):
        db_session.flush()
    db_session.rollback()

    with pytest.raises(ProcessEventConflictError):
        correct_process_event(
            db_session,
            user_pk=user.id,
            opportunity_id=admitted.opportunity.id,
            target_event_id=assessment.id,
            command=ProcessEventCorrection(
                occurred_at=NOW + timedelta(days=3),
                source_kind="user_assertion",
                source_identity="message-fix-again",
                description="second correction is invalid",
            ),
        )

    correction = list_process_events(
        db_session,
        user_pk=user.id,
        opportunity_id=admitted.opportunity.id,
    )[-1]
    with pytest.raises(ProcessEventConflictError):
        correct_process_event(
            db_session,
            user_pk=user.id,
            opportunity_id=admitted.opportunity.id,
            target_event_id=correction.id,
            command=ProcessEventCorrection(
                occurred_at=NOW + timedelta(days=4),
                source_kind="user_assertion",
                source_identity="message-correct-correction",
                description="minimal model rejects correction chains",
            ),
        )


def test_event_and_opportunity_idempotency_reject_different_payload(db_session):
    user = _user(db_session)
    admitted = _create(db_session, user)

    retried = _create(db_session, user)
    assert retried.opportunity.id == admitted.opportunity.id

    with pytest.raises(CareerIdempotencyConflictError):
        _create(db_session, user, job_title="Different Role")

    _append(
        db_session,
        user,
        admitted.opportunity.id,
        "recruiter_contact",
        idempotency_key="event-1",
    )
    with pytest.raises(CareerIdempotencyConflictError):
        _append(
            db_session,
            user,
            admitted.opportunity.id,
            "assessment_invited",
            idempotency_key="event-1",
        )


def test_next_action_time_contract_and_source_lifecycle(db_session):
    user = _user(db_session)
    admitted = _create(db_session, user)
    assessment = _append(
        db_session,
        user,
        admitted.opportunity.id,
        "assessment_invited",
    )

    with pytest.raises(ValidationError):
        NextActionCreate(
            content="完成测评",
            status="suggested",
            time_kind="deadline",
            source_kind="process_event",
            source_identity=assessment.id,
        )

    action = create_next_action(
        db_session,
        user_pk=user.id,
        command=NextActionCreate(
            content="完成测评",
            status="suggested",
            time_kind="deadline",
            due_at=NOW + timedelta(days=5),
            original_time_text="8 月 18 日前",
            source_timezone="Asia/Shanghai",
            source_kind="process_event",
            source_identity=assessment.id,
        ),
    )
    planned = plan_next_action(
        db_session,
        user_pk=user.id,
        action_id=action.id,
        transition=NextActionTransition(
            source_kind="user_assertion",
            source_identity="message-accept-action",
        ),
    )
    completed_event = _append(
        db_session,
        user,
        admitted.opportunity.id,
        "assessment_completed",
    )
    done = complete_next_action(
        db_session,
        user_pk=user.id,
        action_id=action.id,
        transition=NextActionTransition(
            source_kind="process_event",
            source_identity=completed_event.id,
        ),
    )

    assert planned.planned_source_identity == "message-accept-action"
    assert done.status == "done"
    assert done.resolution_source_identity == completed_event.id

    interview = _append(
        db_session,
        user,
        admitted.opportunity.id,
        "interview_scheduled",
    )
    fixed = create_next_action(
        db_session,
        user_pk=user.id,
        command=NextActionCreate(
            content="参加一面",
            status="planned",
            time_kind="fixed",
            starts_at=NOW + timedelta(days=7),
            ends_at=NOW + timedelta(days=7, hours=1),
            original_time_text="8 月 20 日 17:00",
            source_timezone="Asia/Shanghai",
            source_kind="process_event",
            source_identity=interview.id,
        ),
    )
    assert fixed.status == "planned"
    assert fixed.planned_source_kind == "process_event"
    with pytest.raises(NextActionTransitionError):
        close_next_action(
            db_session,
            user_pk=user.id,
            action_id=action.id,
            transition=NextActionClose(
                source_kind="user_assertion",
                source_identity="message-close",
                reason="no longer needed",
            ),
        )


def test_agent_suggestion_cannot_be_created_as_user_plan(db_session):
    user = _user(db_session)

    with pytest.raises(NextActionTransitionError):
        create_next_action(
            db_session,
            user_pk=user.id,
            command=NextActionCreate(
                content="考虑跟进招聘方",
                status="planned",
                time_kind="flexible",
                source_kind="agent_suggestion",
                source_identity="turn-1",
            ),
        )

    with pytest.raises(ValidationError):
        NextActionTransition(
            source_kind="agent_task",
            source_identity="agent-task-1",
        )


def test_owner_isolation_and_read_models(db_session):
    owner = _user(db_session, "owner")
    other = _user(db_session, "other")
    admitted = _create(db_session, owner)
    action = create_next_action(
        db_session,
        user_pk=owner.id,
        command=NextActionCreate(
            content="整理岗位问题",
            status="planned",
            time_kind="flexible",
            source_kind="user_request",
            source_identity="message-plan",
        ),
    )

    assert list_job_opportunities(db_session, user_pk=owner.id) == [
        admitted.opportunity
    ]
    assert list_next_actions(
        db_session,
        user_pk=owner.id,
        statuses={"planned"},
    ) == [action]
    assert list_job_opportunities(db_session, user_pk=other.id) == []
    with pytest.raises(CareerObjectNotFoundError):
        list_process_events(
            db_session,
            user_pk=other.id,
            opportunity_id=admitted.opportunity.id,
        )
    event_row = list_process_events(
        db_session,
        user_pk=owner.id,
        opportunity_id=admitted.opportunity.id,
    )[0]
    with pytest.raises(CareerObjectNotFoundError):
        create_next_action(
            db_session,
            user_pk=other.id,
            command=NextActionCreate(
                content="跨用户动作",
                status="suggested",
                time_kind="flexible",
                source_kind="process_event",
                source_identity=event_row.id,
            ),
        )


def test_user_can_close_planned_action_with_a_traceable_reason(db_session):
    user = _user(db_session)
    action = create_next_action(
        db_session,
        user_pk=user.id,
        command=NextActionCreate(
            content="整理岗位问题",
            status="planned",
            time_kind="flexible",
            source_kind="user_request",
            source_identity="message-create-action",
        ),
    )

    closed = close_next_action(
        db_session,
        user_pk=user.id,
        action_id=action.id,
        transition=NextActionClose(
            source_kind="user_assertion",
            source_identity="message-close-action",
            reason="岗位要求已经变化，不再需要",
        ),
    )

    assert closed.status == "closed"
    assert closed.close_reason == "岗位要求已经变化，不再需要"
    assert closed.resolution_source_identity == "message-close-action"


def test_terminal_opportunity_exits_default_active_list(db_session):
    user = _user(db_session)
    admitted = _create(db_session, user)
    _append(db_session, user, admitted.opportunity.id, "withdrawn")

    assert list_job_opportunities(db_session, user_pk=user.id) == []
    assert list_job_opportunities(
        db_session,
        user_pk=user.id,
        include_archived=True,
    ) == [admitted.opportunity]
    assert db_session.query(JobOpportunity).count() == 1
    assert db_session.query(NextAction).count() == 0
