from __future__ import annotations

import json

import pytest

from app.db.types import utc_now
from app.models.artifact import Artifact, ArtifactVersion
from app.models.career_profile import CareerProfile, CareerProfileDirection
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import JobOpportunity, NextAction
from app.models.pending_submission import PendingSubmission
from app.models.user import User
from app.services.chat import product_object_reference, turn_executor
from app.services.chat.context_assembly_pipeline import (
    AssembledContext,
    PromptRenderer,
    render_historical_user_content,
)
from app.services.chat.product_object_reference import (
    ProductObjectReferenceUnavailableError,
)


class _NonClosingSession:
    def __init__(self, session):
        self.session = session

    def __getattr__(self, name):
        return getattr(self.session, name)

    def close(self):
        pass


def _product_rows(db_session, user: User, *, suffix: str = "one") -> dict[str, str]:
    now = utc_now()
    profile = CareerProfile(
        id=f"cp_{suffix}",
        user_id=user.id,
        personal_facts_json=[
            {"id": "fact-1", "value": {"kind": "skill", "name": "Python"}}
        ],
        version=2,
    )
    direction = CareerProfileDirection(
        id=f"cpd_{suffix}",
        career_profile_id=profile.id,
        label="后端工程师",
        criteria_json={"technologies": ["Python"]},
        lifecycle="active",
        priority=1,
        confirmed_source_kind="user_edit",
        confirmed_at=now,
    )
    opportunity = JobOpportunity(
        id=f"jo_{suffix}",
        user_id=user.id,
        company_name="Example",
        job_title="Backend Engineer",
        phase="in_process",
        current_step="等待二面",
    )
    action = NextAction(
        id=f"na_{suffix}",
        user_id=user.id,
        job_opportunity_id=opportunity.id,
        content="准备系统设计",
        status="planned",
        time_kind="flexible",
        source_kind="user_request",
        source_identity=f"test:{suffix}",
        planned_at=now,
        planned_source_kind="user_assertion",
        planned_source_identity=f"test:{suffix}:planned",
    )
    artifact = Artifact(
        id=f"art_{suffix}",
        user_id=user.id,
        kind="resume",
        creation_key=f"create-{suffix}",
    )
    version = ArtifactVersion(
        id=f"artv_{suffix}",
        artifact_id=artifact.id,
        version_no=1,
        operation_key=f"version-{suffix}",
        title="后端简历",
        content_text="真实保存的简历内容",
        content_format="markdown",
        origin_kind="explicit_save",
    )
    record = InterviewRecord(
        id=f"ir_{suffix}",
        user_id=user.id,
        source="upload",
        title="Example 二面",
        job_opportunity_id=opportunity.id,
        status="completed",
        analysis_json=json.dumps({"overall": {"summary": "表达清楚"}}),
    )
    db_session.add_all(
        [profile, direction, opportunity, action, artifact, version, record]
    )
    db_session.flush()
    return {
        "career_profile": profile.id,
        "career_profile_direction": direction.id,
        "job_opportunity": opportunity.id,
        "next_action": action.id,
        "artifact": artifact.id,
        "interview_record": record.id,
    }


def _refs(rows: dict[str, str]) -> list[dict[str, str]]:
    return [{"kind": kind, "object_id": object_id} for kind, object_id in rows.items()]


def test_closed_routes_reread_every_real_owner_and_reject_cross_tenant(
    db_session,
):
    owner = User(username="object-owner", hashed_password="x")
    other = User(username="object-other", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.flush()
    rows = _product_rows(db_session, owner)
    other_rows = _product_rows(db_session, other, suffix="other")
    db_session.commit()

    resolved = product_object_reference.resolve_product_object_references(
        db_session,
        user_pk=owner.id,
        references=_refs(rows) + [_refs(rows)[0]],
    )
    assert [row.kind for row in resolved] == list(rows)
    assert resolved[0].projection["version"] == 2
    assert resolved[2].projection["current_step"] == "等待二面"
    assert (
        resolved[4].projection["current_version"]["content_text"]
        == "真实保存的简历内容"
    )
    assert resolved[5].projection["analysis"]["overall"]["summary"] == "表达清楚"

    with pytest.raises(ProductObjectReferenceUnavailableError):
        product_object_reference.resolve_product_object_references(
            db_session,
            user_pk=owner.id,
            references=[
                {
                    "kind": "job_opportunity",
                    "object_id": other_rows["job_opportunity"],
                }
            ],
        )


def test_admission_freezes_identity_in_turn_and_history_and_is_idempotent(db_session):
    user = User(username="object-admission", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    rows = _product_rows(db_session, user)
    conversation = Conversation(
        id="object-admission-session",
        user_id=user.id,
        title="T",
        type="general",
    )
    db_session.add(conversation)
    db_session.commit()
    references = [
        {"kind": "job_opportunity", "object_id": rows["job_opportunity"]},
        {"kind": "artifact", "object_id": rows["artifact"]},
    ]

    admitted = turn_executor.admit_submission(
        db_session,
        conversation,
        submission_id="object-admission-input",
        version=1,
        user_id=user.id,
        requested_mode="agent",
        message="请比较这两个对象",
        object_references=references,
    )
    assert admitted.status == "admitted"
    replay = turn_executor.admit_submission(
        db_session,
        conversation,
        submission_id="object-admission-input",
        version=1,
        user_id=user.id,
        requested_mode="agent",
        message="请比较这两个对象",
        object_references=references,
    )
    assert replay.turn_id == admitted.turn_id

    turn = db_session.get(ConversationTurn, admitted.turn_id)
    pending = db_session.get(PendingSubmission, "object-admission-input")
    assert turn.object_references_json == references
    assert pending.object_references_json == references
    message = (
        db_session.query(ConversationMessage)
        .filter_by(conversation_id=conversation.id, role="User")
        .one()
    )
    blocks = json.loads(message.content_blocks_json)
    object_blocks = [
        block for block in blocks if block["type"] == "product_object_reference"
    ]
    assert [(block["kind"], block["object_id"]) for block in object_blocks] == [
        (item["kind"], item["object_id"]) for item in references
    ]
    assert object_blocks[0]["label"] == "Example · Backend Engineer"

    with pytest.raises(turn_executor.SubmissionConflictError):
        turn_executor.admit_submission(
            db_session,
            conversation,
            submission_id="object-admission-input",
            version=1,
            user_id=user.id,
            requested_mode="agent",
            message="请比较这两个对象",
            object_references=[references[0]],
        )


def test_cross_tenant_claim_is_retained_failed_without_turn_or_history(db_session):
    owner = User(username="object-claim-owner", hashed_password="x")
    other = User(username="object-claim-other", hashed_password="x")
    db_session.add_all([owner, other])
    db_session.flush()
    other_rows = _product_rows(db_session, other, suffix="claim-other")
    conversation = Conversation(
        id="object-claim-session",
        user_id=owner.id,
        title="T",
        type="general",
    )
    db_session.add(conversation)
    db_session.commit()

    result = turn_executor.admit_submission(
        db_session,
        conversation,
        submission_id="cross-tenant-reference",
        version=1,
        user_id=owner.id,
        requested_mode="agent",
        message="分析这个岗位",
        object_references=[
            {
                "kind": "job_opportunity",
                "object_id": other_rows["job_opportunity"],
            }
        ],
    )
    assert result.status == "failed"
    assert result.error == product_object_reference.UNAVAILABLE_MESSAGE
    assert db_session.query(ConversationTurn).count() == 0
    assert db_session.query(ConversationMessage).count() == 0


def test_queued_edit_and_retry_preserve_the_versioned_reference_snapshot(db_session):
    user = User(username="object-queue-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    rows = _product_rows(db_session, user, suffix="queue")
    conversation = Conversation(
        id="object-queue-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="object-queue-active",
    )
    active = ConversationTurn(
        id="object-queue-active",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="current",
        status="running",
    )
    db_session.add_all([conversation, active])
    db_session.commit()

    queued = turn_executor.admit_submission(
        db_session,
        conversation,
        submission_id="object-queued-input",
        version=1,
        user_id=user.id,
        requested_mode="agent",
        message="先看材料",
        object_references=[{"kind": "artifact", "object_id": rows["artifact"]}],
    )
    assert queued.status == "queued"
    assert db_session.query(ConversationMessage).count() == 0

    edited = turn_executor.update_pending_submission(
        db_session,
        conversation.id,
        user.id,
        "object-queued-input",
        expected_version=1,
        message="改为看岗位",
        mode="agent",
        question_indexes=[],
        attachment_draft_ids=[],
        object_references=[
            {"kind": "job_opportunity", "object_id": rows["job_opportunity"]}
        ],
    )
    assert edited.version == 2
    assert edited.object_references_json == [
        {"kind": "job_opportunity", "object_id": rows["job_opportunity"]}
    ]

    active.status = "completed"
    conversation.active_turn_id = None
    edited.status = "failed"
    edited.error = "retry"
    db_session.commit()
    retried = turn_executor.retry_pending_submission(
        db_session,
        conversation.id,
        user.id,
        edited.id,
        expected_version=2,
    )
    assert retried.status == "admitted"
    turn = db_session.get(ConversationTurn, retried.turn_id)
    assert turn.object_references_json == edited.object_references_json
    assert db_session.query(ConversationMessage).count() == 1


def test_queued_reference_deleted_before_claim_becomes_failed_hold(db_session):
    user = User(username="object-stale-queue", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    rows = _product_rows(db_session, user, suffix="stale-queue")
    conversation = Conversation(
        id="object-stale-queue-session",
        user_id=user.id,
        title="T",
        type="general",
        active_turn_id="object-stale-queue-active",
    )
    active = ConversationTurn(
        id="object-stale-queue-active",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="current",
        status="running",
        owner_id=turn_executor._WORKER_ID,
    )
    db_session.add_all([conversation, active])
    db_session.commit()
    queued = turn_executor.admit_submission(
        db_session,
        conversation,
        submission_id="object-stale-queued-input",
        version=1,
        user_id=user.id,
        requested_mode="agent",
        message="分析这个方向",
        object_references=[
            {
                "kind": "career_profile_direction",
                "object_id": rows["career_profile_direction"],
            }
        ],
    )
    assert queued.status == "queued"
    db_session.query(CareerProfileDirection).filter_by(
        id=rows["career_profile_direction"]
    ).delete()
    db_session.commit()

    changed, next_turn_id = turn_executor._terminalize(
        db_session,
        active.id,
        allowed_statuses={"running"},
        status="completed",
        error=None,
        owner_id=turn_executor._WORKER_ID,
    )
    assert changed is True
    assert next_turn_id is None
    retained = db_session.get(PendingSubmission, "object-stale-queued-input")
    assert retained.status == "failed"
    assert retained.error == product_object_reference.UNAVAILABLE_MESSAGE
    assert db_session.query(ConversationMessage).count() == 0


def test_execution_reread_fails_closed_after_owner_deletion(db_session, monkeypatch):
    user = User(username="object-delete-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    rows = _product_rows(db_session, user, suffix="delete")
    db_session.commit()
    monkeypatch.setattr(
        product_object_reference,
        "SessionLocal",
        lambda: _NonClosingSession(db_session),
    )
    reference = [{"kind": "job_opportunity", "object_id": rows["job_opportunity"]}]
    context = product_object_reference.build_product_object_context(
        user_pk=user.id,
        references=reference,
    )
    assert "server_reread_product_state" in context
    assert "等待二面" in context

    db_session.query(InterviewRecord).filter_by(
        job_opportunity_id=rows["job_opportunity"]
    ).update({"job_opportunity_id": None})
    db_session.query(NextAction).filter_by(
        job_opportunity_id=rows["job_opportunity"]
    ).update({"job_opportunity_id": None})
    db_session.query(JobOpportunity).filter_by(id=rows["job_opportunity"]).delete()
    db_session.commit()
    with pytest.raises(ProductObjectReferenceUnavailableError):
        product_object_reference.build_product_object_context(
            user_pk=user.id,
            references=reference,
        )


def test_object_projection_is_low_authority_and_adjacent_to_current_query():
    renderer = PromptRenderer()
    context = AssembledContext(
        product_object_context="server-reread data",
        current_input="compare it",
    )
    current_message = renderer.render_current_user_message(context)
    assert current_message.index(
        "[Referenced Product Objects]"
    ) < current_message.index("[Current Query]")
    stable = renderer.render_stable_system_prompt(context, system_prompt="rules")
    assert stable == "rules"
    assert "server-reread data" not in stable

    history = render_historical_user_content(
        {
            "content": "继续分析它",
            "blocks": [
                {
                    "type": "product_object_reference",
                    "kind": "artifact",
                    "object_id": "art_1",
                    "label": "旧标题",
                },
                {"type": "text", "text": "继续分析它"},
            ],
        }
    )
    assert '"object_id": "art_1"' in history
    assert "reread the owner" in history
    assert "继续分析它" in history


@pytest.mark.asyncio
async def test_execution_persists_unavailable_reference_failure(monkeypatch):
    turn = turn_executor.TurnExecution(
        id="object-unavailable-turn",
        conversation_id="object-unavailable-session",
        username="alice",
        user_pk=7,
        mode="agent",
        message="分析它",
        object_references=({"kind": "artifact", "object_id": "art_deleted"},),
    )
    monkeypatch.setattr(turn_executor, "_claim", lambda _turn_id: turn)
    monkeypatch.setattr(
        turn_executor,
        "build_product_object_context",
        lambda **_kwargs: (_ for _ in ()).throw(
            ProductObjectReferenceUnavailableError(
                product_object_reference.UNAVAILABLE_MESSAGE
            )
        ),
    )
    persisted: list[dict] = []
    monkeypatch.setattr(
        turn_executor.transcript_service,
        "complete_background_turn",
        lambda **kwargs: persisted.append(kwargs) or 2,
    )
    finished: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        turn_executor,
        "_finish",
        lambda _turn_id, status, error=None: finished.append((status, error)) or True,
    )
    events: list[dict] = []

    async def append(_turn_id: str, event_json: str):
        events.append(json.loads(event_json))

    monkeypatch.setattr(turn_executor.turn_event_buffer, "append", append)

    await turn_executor.execute_turn(turn.id)

    assert persisted[0]["turn_id"] == turn.id
    assert product_object_reference.UNAVAILABLE_MESSAGE in persisted[0]["ai_msg"]
    assert finished == [("failed", product_object_reference.UNAVAILABLE_MESSAGE)]
    assert [event["type"] for event in events] == ["error", "done"]
