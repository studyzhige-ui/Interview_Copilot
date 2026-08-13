from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_runtime.tool_policy import ToolEffect
from app.agent_runtime.tool_registry import AgentToolContext, registry
from app.db.database import Base
from app.models.artifact import Artifact
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity
from app.models.offer import Offer
from app.models.user import User
from app.schemas.artifact import ArtifactWriteInput
from app.schemas.career_profile import CareerProfileDraftInput, FactDraftChange
from app.schemas.job_opportunity import NextActionCreate
from app.services import artifact_service, career_profile_service
from app.services.career_process_service import create_next_action


NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)


@pytest.fixture
def domain_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _NoCloseSession:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        pass


def _principal(db, prefix: str):
    user = User(
        username=f"{prefix}-{uuid.uuid4().hex}",
        email=f"{prefix}-{uuid.uuid4().hex}@example.test",
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    conversation = Conversation(user_id=user.id, mode="agent")
    db.add(conversation)
    db.flush()
    current = ConversationMessage(
        conversation_id=conversation.id,
        seq=1,
        role="user",
        content="请执行当前明确的产品状态操作",
    )
    old = ConversationMessage(
        conversation_id=conversation.id,
        seq=2,
        role="user",
        content="一条旧的、与当前任务无关的确认",
    )
    db.add_all([current, old])
    db.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message=current.content,
        user_message_seq=current.seq,
        status="running",
    )
    db.add(turn)
    db.flush()
    db.commit()
    ctx = AgentToolContext(
        user_id=user.username,
        user_pk=user.id,
        session_id=conversation.id,
        turn_id=turn.id,
    )
    return user, conversation, turn, current, old, ctx


def _call(name: str, payload: dict, ctx: AgentToolContext):
    return asyncio.run(registry.dispatch(name, payload, ctx))


def _patch_session(monkeypatch, db):
    from app.agent_runtime.tools import career_domains

    monkeypatch.setattr(
        career_domains,
        "SessionLocal",
        lambda: _NoCloseSession(db),
    )
    return career_domains


def _job(db, user: User, suffix: str = "one") -> JobOpportunity:
    row = JobOpportunity(
        user_id=user.id,
        company_name=f"Company {suffix}",
        job_title="Engineer",
        phase="applied",
        current_step="已确认投递",
    )
    db.add(row)
    db.flush()
    return row


def test_domain_tool_surface_is_task_shaped_strict_and_policy_guarded():
    expected = {
        "read_career_domain_state": ToolEffect.READ,
        "confirm_career_profile_change": ToolEffect.INTERNAL_WRITE,
        "review_ability_signals": ToolEffect.INTERNAL_WRITE,
        "manage_next_action": ToolEffect.INTERNAL_WRITE,
        "start_interview_debrief": ToolEffect.INTERNAL_WRITE,
        "analyze_offers": ToolEffect.INTERNAL_WRITE,
        "manage_persistent_task": ToolEffect.INTERNAL_WRITE,
        "record_artifact_submission": ToolEffect.INTERNAL_WRITE,
    }
    schemas = {item["function"]["name"]: item for item in registry.get_openai_schemas()}
    for name, effect in expected.items():
        definition = registry.get(name)
        assert definition is not None
        assert definition.effect is effect
        assert definition.concurrency_safe is (effect is ToolEffect.READ)
        assert name in schemas
        assert schemas[name]["function"]["parameters"]["additionalProperties"] is False

    ctx = AgentToolContext("u", "s", "t", 1)
    cases = [
        (
            "confirm_career_profile_change",
            {"command": {"operation": "upsert_fact"}},
            "请更新我的求职档案",
            True,
        ),
        (
            "review_ability_signals",
            {"command": {"operation": "recompute_interview"}},
            "请重新计算面试能力信号",
            True,
        ),
        (
            "manage_next_action",
            {"command": {"operation": "create"}},
            "请创建下一步行动",
            True,
        ),
        ("start_interview_debrief", {}, "请开始分析面试录音", True),
        ("analyze_offers", {"save_artifact": False}, "请比较这些 Offer", True),
        (
            "manage_persistent_task",
            {"command": {"operation": "pause"}},
            "请暂停这个持续任务",
            True,
        ),
        ("record_artifact_submission", {}, "请记录已投递材料版本", True),
        (
            "manage_next_action",
            {"command": {"operation": "create"}},
            "不要创建下一步行动",
            False,
        ),
        ("analyze_offers", {"save_artifact": False}, "这些 Offer 怎么样", False),
        (
            "manage_next_action",
            {"command": {"operation": "close"}},
            "请创建下一步行动",
            False,
        ),
        (
            "manage_persistent_task",
            {"command": {"operation": "resume"}},
            "请暂停这个持续任务",
            False,
        ),
    ]
    for name, arguments, task, expected_authorized in cases:
        authorized, reversible = registry.policy_traits(name, arguments, ctx, task)
        assert authorized is expected_authorized
        assert reversible is False


def test_profile_commands_require_current_turn_message_and_preserve_candidate_cas(
    monkeypatch,
    domain_db,
):
    _patch_session(monkeypatch, domain_db)
    owner, _conversation, _turn, current, old, ctx = _principal(domain_db, "profile")
    career_profile_service.ensure_career_profile(domain_db, user_pk=owner.id)
    domain_db.commit()

    direct = _call(
        "confirm_career_profile_change",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "upsert_fact",
                "expected_profile_version": 1,
                "fact": {"kind": "skill", "name": "Python"},
            },
        },
        ctx,
    )
    assert direct["profile"]["version"] == 2
    assert direct["profile"]["personal_facts"][0]["confirmed_source_id"] == str(
        current.id
    )

    stale_source = _call(
        "confirm_career_profile_change",
        {
            "confirmation_message_id": old.id,
            "command": {
                "operation": "upsert_fact",
                "expected_profile_version": 2,
                "fact": {"kind": "skill", "name": "Should not persist"},
            },
        },
        ctx,
    )
    assert stale_source["error"] == "current_task_confirmation_required"
    assert (
        career_profile_service.get_career_profile(domain_db, user_pk=owner.id).version
        == 2
    )

    draft = career_profile_service.create_profile_draft_change(
        domain_db,
        user_pk=owner.id,
        draft=CareerProfileDraftInput(
            source_kind="conversation_message",
            source_id=str(current.id),
            proposed_facts=[
                FactDraftChange(
                    operation="upsert",
                    fact={"kind": "skill", "name": "PostgreSQL"},
                )
            ],
        ),
    )
    draft_view = career_profile_service.profile_draft_view(
        domain_db, user_pk=owner.id, draft_id=draft.id
    )
    domain_db.commit()
    resolved = _call(
        "confirm_career_profile_change",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "resolve_candidates",
                "draft_id": draft.id,
                "expected_draft_version": draft_view.version,
                "expected_profile_version": 2,
                "decisions": [
                    {
                        "item_id": draft_view.candidates[0].id,
                        "expected_version": draft_view.candidates[0].version,
                        "decision": "accept",
                    }
                ],
            },
        },
        ctx,
    )
    assert resolved["profile"]["version"] == 3
    assert resolved["draft"]["candidates"][0]["status"] == "accepted"


def test_ability_recompute_dispute_and_domain_read_are_owned(
    monkeypatch,
    domain_db,
):
    _patch_session(monkeypatch, domain_db)
    owner, _conversation, _turn, current, _old, ctx = _principal(domain_db, "ability")
    record = InterviewRecord(
        user_id=owner.id,
        source="mock",
        title="Backend mock",
        status="review_ready",
        analysis_schema_version=3,
        analysis_json=json.dumps(
            {"schema_version": 3, "skill_radar": {"technical_depth": 8.0}}
        ),
        debrief_guidance_text="重点检查系统设计权衡",
        debrief_guidance_version=1,
    )
    domain_db.add(record)
    domain_db.flush()
    domain_db.add(
        InterviewQA(
            record_id=record.id,
            order_idx=0,
            question="How do transactions work?",
            answer="With atomicity and isolation.",
            score=8.0,
            analyzed_at=NOW,
        )
    )
    domain_db.commit()

    recomputed = _call(
        "review_ability_signals",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "recompute_interview",
                "interview_record_id": record.id,
                "reason": "用户要求基于这次复盘重算",
            },
        },
        ctx,
    )
    assert recomputed["ability_signals"][0]["scope_ref_id"] == record.id
    signal = recomputed["ability_signals"][0]
    disputed = _call(
        "review_ability_signals",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "dispute",
                "signal_id": signal["id"],
                "expected_version": signal["version"],
                "reason": "这次样本不足以代表真实水平",
            },
        },
        ctx,
    )
    assert disputed["ability_signal"]["status"] == "disputed"

    state = _call(
        "read_career_domain_state",
        {"sections": ["ability_signals", "interviews"]},
        ctx,
    )
    assert state["ability_signals"][0]["status"] == "disputed"
    assert state["interviews"][0]["debrief_guidance"] == "重点检查系统设计权衡"
    assert state["interviews"][0]["detail_tool"]["name"] == ("read_interview_history")


def test_next_action_full_lifecycle_uses_cas_current_source_and_reminder(
    monkeypatch,
    domain_db,
):
    _patch_session(monkeypatch, domain_db)
    owner, _conversation, _turn, current, _old, ctx = _principal(domain_db, "action")
    job = _job(domain_db, owner)
    domain_db.commit()

    created = _call(
        "manage_next_action",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "create",
                "content": "准备系统设计面试",
                "time_kind": "deadline",
                "due_at": (NOW + timedelta(days=2)).isoformat(),
                "original_time_text": "后天 17:00 前",
                "source_timezone": "Asia/Shanghai",
                "reminder_at": (NOW + timedelta(days=1)).isoformat(),
                "reminder_channel": "in_app",
                "job_opportunity_id": job.id,
                "idempotency_key": "agent-action-one",
            },
        },
        ctx,
    )["next_action"]
    assert created["status"] == "planned"
    assert created["source_identity"] == f"conversation_message:{current.id}"
    assert created["reminder_channel"] == "in_app"

    edited = _call(
        "manage_next_action",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "edit",
                "action_id": created["id"],
                "expected_version": created["version"],
                "content": "准备系统设计终面",
                "time_kind": "deadline",
                "due_at": (NOW + timedelta(days=2)).isoformat(),
                "original_time_text": "后天 17:00 前",
                "source_timezone": "Asia/Shanghai",
                "job_opportunity_id": job.id,
            },
        },
        ctx,
    )["next_action"]
    assert edited["version"] == 1
    stale = _call(
        "manage_next_action",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "complete",
                "action_id": created["id"],
                "expected_version": 0,
            },
        },
        ctx,
    )
    assert stale["error"] == "domain_command_rejected"
    completed = _call(
        "manage_next_action",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "complete",
                "action_id": created["id"],
                "expected_version": edited["version"],
            },
        },
        ctx,
    )["next_action"]
    assert completed["status"] == "done"
    assert completed["resolution_source_identity"] == (
        f"conversation_message:{current.id}"
    )

    suggestion = create_next_action(
        domain_db,
        user_pk=owner.id,
        command=NextActionCreate(
            content="建议核对招聘方联系人",
            status="suggested",
            time_kind="flexible",
            source_kind="agent_suggestion",
            source_identity="turn:suggestion",
            job_opportunity_id=job.id,
        ),
    )
    domain_db.commit()
    planned = _call(
        "manage_next_action",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "plan",
                "action_id": suggestion.id,
                "expected_version": suggestion.version,
            },
        },
        ctx,
    )["next_action"]
    assert planned["status"] == "planned"

    close_target = create_next_action(
        domain_db,
        user_pk=owner.id,
        command=NextActionCreate(
            content="不再需要的建议",
            status="suggested",
            time_kind="flexible",
            source_kind="agent_suggestion",
            source_identity="turn:close-suggestion",
        ),
    )
    domain_db.commit()
    closed = _call(
        "manage_next_action",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "close",
                "action_id": close_target.id,
                "expected_version": close_target.version,
                "reason": "用户明确不再推进",
            },
        },
        ctx,
    )["next_action"]
    assert closed["status"] == "closed"
    assert closed["close_reason"] == "用户明确不再推进"


def _offer(db, owner: User, job: JobOpportunity) -> Offer:
    row = Offer(
        user_id=owner.id,
        job_opportunity_id=job.id,
        terms_json={
            "base_salary_amount": "10000",
            "currency": "USD",
            "pay_period": "monthly",
            "tax_basis": "gross",
            "formality": "written",
            "original_text": "USD 10,000 monthly before tax",
        },
        term_sources_json={},
        source_excerpts_json={"source": {"formality": "written"}},
        creation_operation_key=f"offer-{job.id}",
        creation_operation_fingerprint="a" * 64,
        last_operation_key=f"offer-{job.id}",
        last_operation_fingerprint="a" * 64,
        last_source_kind="user_assertion",
        last_source_identity="conversation_message:1",
        last_source_observed_at=NOW,
    )
    db.add(row)
    db.flush()
    return row


def test_offer_analysis_and_artifact_submission_never_claim_external_action(
    monkeypatch,
    domain_db,
):
    _patch_session(monkeypatch, domain_db)
    owner, _conversation, _turn, current, _old, ctx = _principal(domain_db, "offer")
    other, *_other_values = _principal(domain_db, "other")
    other_ctx = _other_values[-1]
    job = _job(domain_db, owner, "offer")
    offer = _offer(domain_db, owner, job)
    artifact = artifact_service.save_artifact_explicitly(
        domain_db,
        user_pk=owner.id,
        operation_key="application-resume",
        artifact_kind="resume",
        version=ArtifactWriteInput(
            title="Application resume",
            content_text="Exact resume body",
            content_format="markdown",
        ),
    )
    version = artifact_service.get_current_artifact_version(
        domain_db, user_pk=owner.id, artifact_id=artifact.id
    )
    domain_db.commit()

    compared = _call(
        "analyze_offers",
        {
            "offer_ids": [offer.id],
            "base_currency": "CNY",
            "exchange_rates": [
                {
                    "currency": "USD",
                    "rate_to_base": "7.2",
                    "source": {
                        "identity": "central-bank-daily-rate",
                        "observed_at": NOW.isoformat(),
                    },
                }
            ],
            "tax_assumptions": [
                {
                    "offer_id": offer.id,
                    "effective_rate": "0.2",
                    "jurisdiction": "Shanghai",
                    "source": {
                        "identity": "tax-calculation-input",
                        "observed_at": NOW.isoformat(),
                    },
                }
            ],
        },
        ctx,
    )
    assert compared["items"][0]["offer_id"] == offer.id
    assert compared["external_action_performed"] is False
    assert compared["offer_decision_performed"] is False

    saved = _call(
        "analyze_offers",
        {
            "offer_ids": [offer.id],
            "base_currency": "CNY",
            "save_artifact": True,
            "operation_key": "save-offer-comparison",
            "confirmation_message_id": current.id,
        },
        ctx,
    )
    assert saved["artifact_id"] is not None
    assert domain_db.get(Artifact, saved["artifact_id"]) is not None
    assert saved["external_action_performed"] is False

    submission = _call(
        "record_artifact_submission",
        {
            "confirmation_message_id": current.id,
            "operation_key": "record-submission-one",
            "artifact_id": artifact.id,
            "artifact_version_id": version.id,
            "job_opportunity_id": job.id,
        },
        ctx,
    )
    assert submission["submission_snapshot"]["artifact_version_id"] == version.id
    assert submission["submission_snapshot"]["basis"] == "user_confirmation"
    assert submission["external_action_performed"] is False
    assert "did not submit" in submission["execution_note"]

    other_current = _other_values[2]
    hidden = _call(
        "record_artifact_submission",
        {
            "confirmation_message_id": other_current.id,
            "operation_key": "cross-owner-submission",
            "artifact_id": artifact.id,
            "artifact_version_id": version.id,
            "job_opportunity_id": job.id,
        },
        other_ctx,
    )
    assert hidden["error"] == "not_found_or_not_owned"
    assert other.id != owner.id


def test_persistent_task_lifecycle_and_manual_admission_never_mean_completion(
    monkeypatch,
    domain_db,
):
    career_domains = _patch_session(monkeypatch, domain_db)
    _owner, _conversation, _turn, current, _old, ctx = _principal(
        domain_db, "automation"
    )
    created = _call(
        "manage_persistent_task",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "create",
                "title": "每周复盘",
                "instruction": "汇总本周求职进展并给出下周计划",
                "trigger": {
                    "kind": "scheduled",
                    "schedule": "0 9 * * 1",
                    "timezone": "Asia/Shanghai",
                },
                "read_scope": ["career_state"],
                "action_scope": [],
                "allowed_tool_names": ["read_career_domain_state"],
                "idempotency_key": "weekly-review-one",
            },
        },
        ctx,
    )
    task = created["persistent_task"]
    assert task["state"] == "active"
    assert created["future_run_completed"] is False

    paused = _call(
        "manage_persistent_task",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "pause",
                "task_id": task["id"],
                "expected_version": task["version"],
            },
        },
        ctx,
    )["persistent_task"]
    assert paused["state"] == "paused"
    resumed = _call(
        "manage_persistent_task",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "resume",
                "task_id": task["id"],
                "expected_version": paused["version"],
            },
        },
        ctx,
    )["persistent_task"]
    assert resumed["state"] == "active"

    monkeypatch.setattr(
        career_domains._persistent_tasks(),
        "dispatch_automation_run",
        lambda admission, runner: bool(admission.should_dispatch),
    )
    triggered = _call(
        "manage_persistent_task",
        {
            "confirmation_message_id": current.id,
            "command": {
                "operation": "manual_trigger",
                "task_id": task["id"],
                "occurred_at": NOW.isoformat(),
                "summary": "用户现在要求运行一次",
                "idempotency_key": "weekly-review-manual-one",
            },
        },
        ctx,
    )
    assert triggered["status"] in {"admitted", "pending", "already_admitted"}
    assert triggered["run_completed"] is False
    assert triggered["external_action_performed"] is False

    state = _call(
        "read_career_domain_state",
        {
            "sections": ["persistent_tasks"],
            "persistent_task_id": task["id"],
        },
        ctx,
    )
    assert state["persistent_tasks"][0]["id"] == task["id"]
    assert state["persistent_task_triggers"][0]["source_identity"] == (
        f"conversation_message:{current.id}"
    )


def test_interview_debrief_returns_real_processing_identity_not_completion(
    monkeypatch,
    domain_db,
):
    _patch_session(monkeypatch, domain_db)
    owner, _conversation, _turn, current, _old, ctx = _principal(domain_db, "debrief")
    asset = FileAsset(
        user_id=owner.id,
        purpose="interview_audio",
        original_filename="interview.mp3",
        object_key=f"uploads/{owner.id}/interview.mp3",
        storage_uri=f"s3://test/{owner.id}/interview.mp3",
        content_type="audio/mpeg",
        size_bytes=123,
        upload_status="uploaded",
        validation_status="passed",
    )
    domain_db.add(asset)
    domain_db.commit()

    from app.services.interview import analysis_intake

    monkeypatch.setattr(
        analysis_intake,
        "dispatch_interview_analysis",
        lambda record_id, language: SimpleNamespace(id=f"task:{record_id}:{language}"),
    )

    def set_status(record_id, status, **values):
        row = domain_db.get(InterviewRecord, record_id)
        row.status = status
        if values.get("celery_task_id") is not None:
            row.celery_task_id = values["celery_task_id"]
        domain_db.add(row)
        domain_db.commit()

    monkeypatch.setattr(
        analysis_intake.interview_record_service, "set_status", set_status
    )
    started = _call(
        "start_interview_debrief",
        {
            "confirmation_message_id": current.id,
            "audio_file_asset_id": asset.id,
            "jd_text": "Backend engineer role focused on distributed systems.",
            "language": "en",
        },
        ctx,
    )
    assert started["status"] == "processing"
    assert started["analysis_completed"] is False
    assert started["external_action_performed"] is False
    record = domain_db.get(InterviewRecord, started["interview_record_id"])
    assert record is not None
    assert record.audio_file_asset_id == asset.id
    assert record.celery_task_id == started["background_task_id"]
    assert domain_db.get(FileAsset, asset.id).upload_status == "consumed"
