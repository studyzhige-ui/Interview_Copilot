from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.artifact import Artifact, ArtifactSubmissionSnapshot, ArtifactVersion
from app.models.career_profile import CareerProfile, CareerProfileDirection
from app.models.job_opportunity import JobOpportunity, NextAction, ProcessEvent
from app.models.offer import Offer
from app.models.user import User
from app.schemas.career_insights import (
    ExchangeRateAssumption,
    NotificationPreferenceUpdate,
    OfferAnalysisRequest,
    TaxAssumption,
)
from app.schemas.job_opportunity import NextActionCreate, NextActionEdit
from app.schemas.offer import OfferSourceInput, OfferTermsInput
from app.services.career_process_service import (
    NextActionTransitionError,
    create_next_action,
    edit_next_action,
)
from app.services.funnel_analysis_service import analyze_funnel
from app.services.offer_analysis_service import compare_offers
from app.services.offer_service import record_current_offer
from app.services.reminder_service import (
    build_next_action_agenda,
    deliver_due_reminders,
    update_notification_preference,
)


def _user(db_session, username: str = "insights") -> User:
    row = User(username=username, email=f"{username}@example.com", hashed_password="x")
    db_session.add(row)
    db_session.flush()
    return row


def _job(db_session, user: User, suffix: str = "1") -> JobOpportunity:
    row = JobOpportunity(
        user_id=user.id,
        company_name=f"Company {suffix}",
        job_title="Engineer",
        phase="applied",
        current_step="已确认投递",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_next_action_typed_links_cas_dedupe_and_agenda(db_session):
    user = _user(db_session)
    job = _job(db_session, user)
    start = datetime.now(UTC) + timedelta(hours=2)
    command = NextActionCreate(
        content="参加技术面试",
        status="planned",
        time_kind="fixed",
        source_kind="user_request",
        source_identity="ui:1",
        job_opportunity_id=job.id,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        original_time_text="今天下午",
        source_timezone="Asia/Shanghai",
        idempotency_key="one",
    )
    action = create_next_action(db_session, user_pk=user.id, command=command)
    duplicate = create_next_action(
        db_session,
        user_pk=user.id,
        command=command.model_copy(
            update={"source_identity": "ui:2", "idempotency_key": "two"}
        ),
    )
    assert duplicate.id == action.id

    overlapping = create_next_action(
        db_session,
        user_pk=user.id,
        command=command.model_copy(
            update={
                "content": "招聘方沟通",
                "source_identity": "ui:3",
                "idempotency_key": "three",
                "starts_at": start + timedelta(minutes=30),
                "ends_at": start + timedelta(hours=2),
            }
        ),
    )
    agenda = build_next_action_agenda(db_session, user_pk=user.id)
    assert {item.action.id for item in agenda.items if item.bucket == "conflict"} == {
        action.id,
        overlapping.id,
    }

    edited = edit_next_action(
        db_session,
        user_pk=user.id,
        action_id=action.id,
        command=NextActionEdit(
            expected_version=0,
            content="参加技术终面",
            time_kind="fixed",
            job_opportunity_id=job.id,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            original_time_text="今天下午",
            source_timezone="Asia/Shanghai",
        ),
    )
    assert edited.version == 1
    with pytest.raises(NextActionTransitionError):
        edit_next_action(
            db_session,
            user_pk=user.id,
            action_id=action.id,
            command=NextActionEdit(
                expected_version=0,
                content="stale",
                time_kind="flexible",
                job_opportunity_id=job.id,
            ),
        )


def test_reminder_scheduler_respects_quiet_hours(db_session):
    user = _user(db_session, "reminder")
    now = datetime(2026, 8, 13, 15, 0, tzinfo=UTC)  # 23:00 Asia/Shanghai
    preference = update_notification_preference(
        db_session,
        user_pk=user.id,
        command=NotificationPreferenceUpdate(
            expected_version=0,
            enabled=True,
            timezone="Asia/Shanghai",
            quiet_start="22:00",
            quiet_end="08:00",
        ),
    )
    assert preference.version == 1
    action = NextAction(
        user_id=user.id,
        content="完成测评",
        status="planned",
        time_kind="deadline",
        due_at=now + timedelta(days=1),
        original_time_text="明天",
        source_timezone="Asia/Shanghai",
        source_kind="user_request",
        source_identity="ui:reminder",
        planned_at=now,
        planned_source_kind="user_assertion",
        planned_source_identity="ui:reminder",
        reminder_at=now,
        reminder_next_attempt_at=now,
        reminder_channel="in_app",
    )
    db_session.add(action)
    db_session.flush()
    result = deliver_due_reminders(db_session, due_at=now)
    assert result["deferred_quiet"] == 1
    assert action.reminder_delivered_at is None
    assert action.reminder_next_attempt_at == datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
    result = deliver_due_reminders(
        db_session, due_at=datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
    )
    assert result["delivered"] == 1
    assert action.reminder_delivered_at is not None


def test_agenda_uses_user_timezone_and_conflicts_same_point_events(db_session):
    user = _user(db_session, "agenda-timezone")
    update_notification_preference(
        db_session,
        user_pk=user.id,
        command=NotificationPreferenceUpdate(
            expected_version=0,
            enabled=True,
            timezone="Asia/Shanghai",
        ),
    )
    now = datetime(2026, 8, 13, 15, 30, tzinfo=UTC)  # 23:30 local
    start = datetime(2026, 8, 13, 16, 30, tzinfo=UTC)  # next local day
    for index, content in enumerate(("面试 A", "面试 B")):
        create_next_action(
            db_session,
            user_pk=user.id,
            command=NextActionCreate(
                content=content,
                status="planned",
                time_kind="fixed",
                source_kind="user_request",
                source_identity=f"ui:point:{index}",
                starts_at=start,
                original_time_text="8 月 14 日 00:30",
                source_timezone="Asia/Shanghai",
            ),
        )
    later = create_next_action(
        db_session,
        user_pk=user.id,
        command=NextActionCreate(
            content="第二天单独事项",
            status="planned",
            time_kind="fixed",
            source_kind="user_request",
            source_identity="ui:later",
            starts_at=start + timedelta(hours=2),
            original_time_text="8 月 14 日 02:30",
            source_timezone="Asia/Shanghai",
        ),
    )
    agenda = build_next_action_agenda(db_session, user_pk=user.id, at=now)
    assert sum(item.bucket == "conflict" for item in agenda.items) == 2
    assert next(item for item in agenda.items if item.action.id == later.id).bucket == (
        "upcoming"
    )


def test_funnel_uses_submission_event_snapshot_and_reports_coverage(db_session):
    user = _user(db_session, "funnel")
    profile = CareerProfile(user_id=user.id, personal_facts_json=[], version=2)
    db_session.add(profile)
    db_session.flush()
    direction = CareerProfileDirection(
        career_profile_id=profile.id,
        label="Backend",
        criteria_json={},
        lifecycle="active",
        priority=0,
        confirmed_source_kind="user_edit",
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(direction)
    job = _job(db_session, user, "funnel")
    db_session.flush()
    applied_at = datetime(2026, 7, 1, tzinfo=UTC)
    application = ProcessEvent(
        job_opportunity_id=job.id,
        sequence=1,
        operation="assert",
        kind="application_submitted",
        occurred_at=applied_at,
        observed_at=applied_at,
        source_kind="user_assertion",
        source_identity="message:1",
        description="submitted",
        idempotency_key="event:1",
        analysis_context_json={
            "career_profile_version": 2,
            "directions": [{"id": direction.id, "label": "Backend"}],
            "channel": "referral",
            "jd_snapshot_identity": None,
        },
    )
    interview = ProcessEvent(
        job_opportunity_id=job.id,
        sequence=2,
        operation="assert",
        kind="interview_scheduled",
        occurred_at=applied_at + timedelta(days=5),
        observed_at=applied_at + timedelta(days=5),
        source_kind="user_assertion",
        source_identity="message:2",
        description="interview",
        idempotency_key="event:2",
        analysis_context_json={},
    )
    artifact = Artifact(user_id=user.id, kind="resume", creation_key="resume")
    db_session.add_all([application, interview, artifact])
    db_session.flush()
    version = ArtifactVersion(
        artifact_id=artifact.id,
        version_no=1,
        operation_key="v1",
        title="Resume",
        content_text="x",
        content_format="plain_text",
        origin_kind="explicit_save",
    )
    db_session.add(version)
    db_session.flush()
    db_session.add(
        ArtifactSubmissionSnapshot(
            user_id=user.id,
            operation_key="submission",
            job_opportunity_id=job.id,
            artifact_id=artifact.id,
            artifact_version_id=version.id,
            basis="user_confirmation",
            confirmation_message_id=1,
            submitted_at=applied_at,
        )
    )
    db_session.flush()
    report = analyze_funnel(db_session, user_pk=user.id)
    assert report.coverage.sample_count == 1
    assert report.coverage.submitted_material_count == 1
    assert report.coverage.jd_snapshot_count == 0
    assert report.groups[0].direction_label == "Backend"
    assert (
        next(
            stage for stage in report.groups[0].stages if stage.stage == "in_process"
        ).median_wait_hours
        == 120
    )
    assert "不能直接归因为用户能力" in report.interpretation_limit


def test_offer_comparison_keeps_assumptions_out_of_offer_facts(db_session):
    user = _user(db_session, "offers")
    profile = CareerProfile(user_id=user.id, personal_facts_json=[], version=1)
    db_session.add(profile)
    db_session.flush()
    db_session.add(
        CareerProfileDirection(
            career_profile_id=profile.id,
            label="Backend",
            criteria_json={
                "locations": ["Shanghai"],
                "salary_min": 500000,
                "salary_currency": "CNY",
            },
            lifecycle="active",
            priority=0,
            confirmed_source_kind="user_edit",
            confirmed_at=datetime.now(UTC),
        )
    )
    job = _job(db_session, user, "offer")
    offer = Offer(
        user_id=user.id,
        job_opportunity_id=job.id,
        terms_json={
            "base_salary_amount": "10000",
            "currency": "USD",
            "pay_period": "monthly",
            "tax_basis": "gross",
        },
        term_sources_json={},
        source_excerpts_json={"x": {"formality": "written"}},
        creation_operation_key="create",
        creation_operation_fingerprint="x" * 64,
        last_operation_key="create",
        last_operation_fingerprint="x" * 64,
        last_source_kind="user_assertion",
        last_source_identity="1",
        last_source_observed_at=datetime.now(UTC),
    )
    db_session.add(offer)
    db_session.flush()
    offer_action = create_next_action(
        db_session,
        user_pk=user.id,
        command=NextActionCreate(
            content="核对 Offer 条款",
            status="planned",
            time_kind="flexible",
            source_kind="user_request",
            source_identity="ui:offer-action",
            offer_id=offer.id,
        ),
    )
    assert offer_action.job_opportunity_id == job.id
    comparison_command = OfferAnalysisRequest(
        offer_ids=[offer.id],
        base_currency="CNY",
        exchange_rates=[
            ExchangeRateAssumption(
                currency="USD",
                rate_to_base=Decimal("7.2"),
                source={
                    "identity": "central-bank-daily-rate",
                    "observed_at": datetime.now(UTC),
                },
            )
        ],
    )
    response = compare_offers(
        db_session,
        user_pk=user.id,
        command=comparison_command,
    )
    assert response.items[0].annual_base_in_base_currency == "864000.00"
    assert "annual" not in offer.terms_json
    assert response.items[0].estimated_after_tax_cash is None
    assert response.career_profile_constraints == [
        "Backend（active）：地点=Shanghai；薪资范围=>=500000 CNY"
    ]
    assert "已确认求职档案约束" in response.report_markdown
    assert "Offer 条款事实来源与观察时点" in response.report_markdown
    assert "central-bank-daily-rate" in response.report_markdown

    saved_command = comparison_command.model_copy(
        update={"save_artifact": True, "operation_key": "offer-compare-save"}
    )
    saved = compare_offers(db_session, user_pk=user.id, command=saved_command)
    retried = compare_offers(db_session, user_pk=user.id, command=saved_command)
    assert saved.artifact_id == retried.artifact_id
    assert "生成时间" not in saved.report_markdown

    with pytest.raises(ValueError):
        compare_offers(
            db_session,
            user_pk=user.id,
            command=OfferAnalysisRequest(
                offer_ids=[offer.id],
                base_currency="CNY",
                exchange_rates=[
                    ExchangeRateAssumption(
                        currency="CNY",
                        rate_to_base=Decimal("7.2"),
                        source={
                            "identity": "bad-base-rate",
                            "observed_at": datetime.now(UTC),
                        },
                    )
                ],
            ),
        )

    offer.terms_json = {
        **offer.terms_json,
        "tax_basis": "net",
        "equity_text": "Options subject to vesting",
    }
    net_response = compare_offers(
        db_session,
        user_pk=user.id,
        command=OfferAnalysisRequest(
            offer_ids=[offer.id],
            base_currency="CNY",
            exchange_rates=[
                ExchangeRateAssumption(
                    currency="USD",
                    rate_to_base=Decimal("7.2"),
                    source={
                        "identity": "central-bank-daily-rate",
                        "observed_at": datetime.now(UTC),
                    },
                )
            ],
            tax_assumptions=[
                TaxAssumption(
                    offer_id=offer.id,
                    effective_rate=Decimal("0.2"),
                    jurisdiction="CN",
                    source={
                        "identity": "tax-reference",
                        "observed_at": datetime.now(UTC),
                    },
                )
            ],
        ),
    )
    assert net_response.items[0].estimated_after_tax_cash == "864000.00"
    assert net_response.items[0].estimated_total_value is None
    assert any(
        "未使用额外有效税率" in item for item in net_response.items[0].assumptions
    )

    with pytest.raises(ValueError):
        OfferAnalysisRequest(
            offer_ids=[offer.id],
            base_currency="CNY",
            tax_assumptions=[
                TaxAssumption(
                    offer_id="offer_not_selected",
                    effective_rate=Decimal("0.2"),
                    jurisdiction="CN",
                    source={
                        "identity": "tax-reference",
                        "observed_at": datetime.now(UTC),
                    },
                )
            ],
        )


def test_offer_deadline_derives_one_source_typed_suggestion(db_session):
    user = _user(db_session, "offer-deadline")
    job = _job(db_session, user, "deadline")
    deadline = datetime.now(UTC) + timedelta(days=3)
    offer = record_current_offer(
        db_session,
        user_pk=user.id,
        job_opportunity_id=job.id,
        operation_key="offer-deadline-create",
        terms=OfferTermsInput(
            response_deadline=deadline,
            response_deadline_text="本周日北京时间 18:00 前",
            response_deadline_timezone="Asia/Shanghai",
            formality="written",
            original_text="Please respond in three days.",
        ),
        source=OfferSourceInput(
            kind="user_assertion",
            identity="message:offer",
            observed_at=datetime.now(UTC),
        ),
        job_owner_checker=lambda *_args: True,
        source_checker=lambda *_args: True,
    )
    action = db_session.query(NextAction).filter(NextAction.offer_id == offer.id).one()
    assert action.status == "suggested"
    assert action.time_kind == "deadline"
    assert action.source_kind == "offer"
    assert action.due_at == deadline
    assert action.original_time_text == "本周日北京时间 18:00 前"
    assert action.source_timezone == "Asia/Shanghai"
