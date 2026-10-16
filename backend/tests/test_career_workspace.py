import uuid
import pytest
from app.career.application import workspace, documents, artifacts, process
from app.models.artifact import ArtifactVersion, ArtifactSubmissionSnapshot
from app.schemas.career_workspace import (
    JobCreate,
    JobEdit,
    StageChange,
    DocumentCreate,
    DraftSave,
    DocumentPublish,
    ResumeDocument,
)
from app.db.types import utc_now


def create_job(db, user):
    return workspace.create_job(
        db,
        user.id,
        JobCreate(
            operation_key=str(uuid.uuid4()),
            company_name="示例科技",
            job_title="Python 工程师",
            description="负责 Agent 应用与数据服务",
        ),
    )


def move(db, user, job, stage, **extra):
    return workspace.change_stage(
        db,
        user.id,
        job["id"],
        StageChange(
            expected_version=job["version"],
            operation_key=str(uuid.uuid4()),
            stage=stage,
            occurred_at=utc_now(),
            **extra,
        ),
    )


def test_search_beyond_first_hundred_and_detail_ownership(db, owners):
    user, foreign = owners
    for i in range(105):
        workspace.create_job(
            db,
            user.id,
            JobCreate(
                operation_key=str(uuid.uuid4()),
                company_name=f"公司{i}",
                job_title="工程师",
            ),
        )
    assert workspace.list_jobs(db, user.id, limit=30)["total"] == 105
    match = workspace.list_jobs(db, user.id, q="公司0")["items"][0]
    assert workspace.detail(db, user.id, match["id"])["id"] == match["id"]
    with pytest.raises(process.CareerObjectNotFoundError):
        workspace.detail(db, foreign.id, match["id"])


def test_current_stage_reopens_without_losing_historical_facts(db, owners):
    user, _ = owners
    job = create_job(db, user)
    job = move(db, user, job, "interview")
    assert job["stage"] == "interview"
    job = move(db, user, job, "applied")
    assert job["stage"] == "applied"
    job = move(db, user, job, "closed", outcome="withdrawn")
    assert job["outcome"] == "withdrawn"
    job = move(db, user, job, "saved")
    assert job["stage"] == "saved" and job["outcome"] is None
    assert len(job["events"]) == 5


def test_document_draft_publish_exact_submission_and_retry(db, owners):
    user, foreign = owners
    data = ResumeDocument(
        name="张同学",
        sections=[{"id": "project", "title": "项目", "content": "Python 工程"}],
    )
    doc = documents.create_document(
        db,
        user.id,
        DocumentCreate(title="后端简历", operation_key="create-resume", data=data),
    )
    saved = documents.save_draft(
        db,
        user.id,
        doc["artifact_id"],
        DraftSave(
            expected_revision=0,
            base_version_id=doc["current_version_id"],
            title="后端简历",
            data=data.model_copy(update={"headline": "工程师"}),
        ),
    )
    assert (
        db.query(ArtifactVersion).filter_by(artifact_id=doc["artifact_id"]).count() == 1
    )
    with pytest.raises(artifacts.ArtifactConflictError):
        documents.save_draft(
            db,
            user.id,
            doc["artifact_id"],
            DraftSave(
                expected_revision=0,
                base_version_id=doc["current_version_id"],
                title="过期",
                data=data,
            ),
        )
    pub = DocumentPublish(
        expected_revision=saved["revision"], operation_key="publish-resume"
    )
    published = documents.publish(db, user.id, doc["artifact_id"], pub)
    assert (
        documents.publish(db, user.id, doc["artifact_id"], pub)["current_version_id"]
        == published["current_version_id"]
    )
    job = create_job(db, user)
    command = StageChange(
        expected_version=job["version"],
        operation_key="submit",
        stage="applied",
        occurred_at=utc_now(),
        version_ids=[published["current_version_id"]],
        channel="官网",
    )
    workspace.change_stage(db, user.id, job["id"], command)
    workspace.change_stage(db, user.id, job["id"], command)
    assert db.query(ArtifactSubmissionSnapshot).count() == 1
    assert (
        workspace.detail(db, user.id, job["id"])["submissions"][0]["submitted_at"]
        == command.occurred_at
    )
    changed = documents.save_draft(
        db,
        user.id,
        doc["artifact_id"],
        DraftSave(
            expected_revision=published["revision"],
            base_version_id=published["current_version_id"],
            title="修改后的简历",
            data=data,
        ),
    )
    documents.publish(
        db,
        user.id,
        doc["artifact_id"],
        DocumentPublish(
            expected_revision=changed["revision"], operation_key="publish-again"
        ),
    )
    assert (
        workspace.detail(db, user.id, job["id"])["submissions"][0]["version"]["id"]
        == published["current_version_id"]
    )
    with pytest.raises(artifacts.ArtifactNotFoundError):
        documents.get_draft(db, foreign.id, doc["artifact_id"])


def test_draft_timeout_retry_and_publication_command_binding(db, owners):
    user, _ = owners
    data = ResumeDocument(name="可恢复草稿")
    doc = documents.create_document(
        db,
        user.id,
        DocumentCreate(title="重试", operation_key="retry-create", data=data),
    )
    save = DraftSave(
        expected_revision=0,
        base_version_id=doc["current_version_id"],
        title="新标题",
        data=data,
        operation_key="retry-save",
    )
    first = documents.save_draft(db, user.id, doc["artifact_id"], save)
    replay = documents.save_draft(db, user.id, doc["artifact_id"], save)
    assert first["revision"] == replay["revision"] == 1
    with pytest.raises(artifacts.ArtifactConflictError):
        documents.save_draft(
            db,
            user.id,
            doc["artifact_id"],
            save.model_copy(update={"title": "同键不同内容"}),
        )
    published = documents.publish(
        db,
        user.id,
        doc["artifact_id"],
        DocumentPublish(expected_revision=1, operation_key="retry-publish"),
    )
    assert published["revision"] == 2
    with pytest.raises(artifacts.ArtifactConflictError):
        documents.publish(
            db,
            user.id,
            doc["artifact_id"],
            DocumentPublish(expected_revision=2, operation_key="retry-publish"),
        )
    artifacts.archive_artifact(db, user_pk=user.id, artifact_id=doc["artifact_id"])
    assert documents.get_draft(db, user.id, doc["artifact_id"])["archived"]
    with pytest.raises(artifacts.ArtifactArchivedError):
        documents.save_draft(db, user.id, doc["artifact_id"], save)
    artifacts.restore_artifact(db, user_pk=user.id, artifact_id=doc["artifact_id"])
    assert not documents.get_draft(db, user.id, doc["artifact_id"])["archived"]


def test_database_pages_and_stage_counts_share_effective_projection(db, owners):
    user, _ = owners
    job = create_job(db, user)
    interview = move(db, user, job, "interview")
    move(db, user, interview, "closed", outcome="rejected")
    assert workspace.list_jobs(db, user.id)["counts"]["closed"] == 1
    assert workspace.list_jobs(db, user.id)["total"] == 0
    job = workspace.detail(db, user.id, job["id"])
    reopened = move(db, user, job, "screening")
    rows = workspace.list_jobs(db, user.id, stage="screening", offset=1, limit=1)
    assert rows["total"] == rows["counts"]["screening"] == 1
    assert rows["items"] == []
    assert reopened["stage"] == "screening"


def test_structured_document_validation_and_text_are_consistent():
    from pydantic import ValidationError
    from app.schemas.artifact import ArtifactWriteInput

    with pytest.raises(ValidationError):
        ArtifactWriteInput(
            title="无效文档", content_text="text", document_json={"sections": "invalid"}
        )
    data = ResumeDocument(name="真实内容")
    version = ArtifactWriteInput(
        title="有效文档", content_text="过期文本", document_json=data.model_dump()
    )
    assert version.content_text == data.plain_text()
    with pytest.raises(ValidationError):
        ResumeDocument(
            sections=[
                {"id": "duplicate", "title": "A"},
                {"id": "duplicate", "title": "B"},
            ]
        )


def test_recorded_offer_updates_pipeline_and_deadline_atomically(db, owners):
    from datetime import timedelta
    from app.career.application import offers
    from app.schemas.offer import OfferSourceInput, OfferTermsInput

    user, _ = owners
    job = create_job(db, user)
    now = utc_now()
    command = dict(
        user_pk=user.id,
        job_opportunity_id=job["id"],
        operation_key="received-offer",
        terms=OfferTermsInput(
            formality="written",
            original_text="欢迎加入，周五前回复",
            response_deadline=now + timedelta(days=2),
        ),
        source=OfferSourceInput(
            kind="artifact", identity="verified-test-source", observed_at=now
        ),
        job_owner_checker=lambda *_: True,
        source_checker=lambda *_: True,
    )
    offer = offers.record_current_offer(db, **command)
    assert offers.record_current_offer(db, **command).id == offer.id
    result = workspace.detail(db, user.id, job["id"])
    assert result["stage"] == "offer"
    assert len([e for e in result["events"] if e["kind"] == "offer_received"]) == 1
    assert len(result["actions"]) == 1


def test_correcting_old_stage_description_does_not_reopen_it_as_current(db, owners):
    from app.schemas.job_opportunity import ProcessEventCorrection

    user, _ = owners
    job = move(db, user, create_job(db, user), "applied")
    application = job["events"][-1]
    job = move(db, user, job, "offer")
    process.correct_process_event(
        db,
        user_pk=user.id,
        opportunity_id=job["id"],
        target_event_id=application["id"],
        command=ProcessEventCorrection(
            replacement_kind="application_submitted",
            occurred_at=application["occurred_at"],
            source_kind="user_assertion",
            source_identity="correction",
            description="补充说明：官网投递",
            idempotency_key="correct-old-stage",
        ),
    )
    assert workspace.detail(db, user.id, job["id"])["stage"] == "offer"


def test_job_edit_conflict_and_archive_are_separate_from_outcome(db, owners):
    user, _ = owners
    job = create_job(db, user)
    command = JobEdit(
        expected_version=job["version"],
        company_name="新公司",
        job_title="工程师",
        hidden=True,
    )
    edited = workspace.edit_job(db, user.id, job["id"], command)
    assert edited["hidden"] and edited["outcome"] is None
    assert workspace.list_jobs(db, user.id)["total"] == 0
    assert workspace.list_jobs(db, user.id, hidden=True)["total"] == 1
    assert workspace.list_jobs(db, user.id, hidden=True)["counts"]["saved"] == 1
    from app.api.workspace import overview

    assert overview(current_user=user, db=db).active_opportunities == 0
    with pytest.raises(process.ProcessEventConflictError):
        workspace.edit_job(db, user.id, job["id"], command)


def test_home_resolves_merged_interviews_and_hides_archived_canonical_job(db, owners):
    from datetime import timedelta
    from app.api.workspace import overview
    from app.models.job_opportunity import JobOpportunityMerge
    from app.models.interview_record import InterviewRecord

    user, other = owners
    canonical, duplicate = create_job(db, user), create_job(db, user)
    create_job(db, other)
    db.add(
        JobOpportunityMerge(
            user_id=user.id,
            duplicate_opportunity_id=duplicate["id"],
            canonical_opportunity_id=canonical["id"],
            operation_key=str(uuid.uuid4()),
            reason="用户确认重复",
            confirmation_source_identity="test:merge",
        )
    )
    db.add(
        InterviewRecord(
            user_id=user.id,
            job_opportunity_id=duplicate["id"],
            source="invitation",
            invitation_operation_id=str(uuid.uuid4()),
            scheduled_start_at=utc_now() + timedelta(days=1),
        )
    )
    db.flush()
    home = overview(current_user=user, db=db)
    assert home.active_opportunities == 1
    assert [item.opportunity_id for item in home.upcoming_interviews] == [
        canonical["id"]
    ]
    workspace.edit_job(
        db,
        user.id,
        canonical["id"],
        JobEdit(
            expected_version=canonical["version"],
            company_name=canonical["company_name"],
            job_title=canonical["job_title"],
            hidden=True,
        ),
    )
    home = overview(current_user=user, db=db)
    assert home.active_opportunities == 0 and home.upcoming_interviews == []


def test_submission_failure_rolls_back_event_and_snapshot_together(db, owners):
    user, _ = owners
    job = create_job(db, user)
    before = len(job["events"])
    with pytest.raises(process.CareerObjectNotFoundError):
        with db.begin_nested():
            move(db, user, job, "applied", version_ids=["missing-version"])
    assert len(workspace.detail(db, user.id, job["id"])["events"]) == before


def test_empty_document_does_not_become_default_interview_resume(db, owners):
    from app.career.application.resumes.resume_artifact_service import (
        list_resume_artifacts,
    )

    user, _ = owners
    documents.create_document(
        db,
        user.id,
        DocumentCreate(
            title="空白简历",
            operation_key="empty",
            data=ResumeDocument(
                sections=[{"id": "experience", "title": "工作经历", "content": ""}]
            ),
        ),
    )
    assert list_resume_artifacts(db, user_pk=user.id) == []


def test_clearing_a_formal_resume_removes_stale_ready_and_default_state(db, owners):
    from app.career.application.resumes import resume_artifact_service as resumes

    user, _ = owners
    doc = documents.create_document(
        db,
        user.id,
        DocumentCreate(
            title="清空测试",
            operation_key="clear-resume",
            data=ResumeDocument(name="已填写"),
        ),
    )
    saved = documents.save_draft(
        db,
        user.id,
        doc["artifact_id"],
        DraftSave(
            expected_revision=0,
            base_version_id=doc["current_version_id"],
            title="已清空",
            data=ResumeDocument(),
        ),
    )
    documents.publish(
        db,
        user.id,
        doc["artifact_id"],
        DocumentPublish(
            expected_revision=saved["revision"], operation_key="publish-empty"
        ),
    )
    owned = resumes.resolve_owned_resume(
        db, user_pk=user.id, resume_id=doc["artifact_id"]
    )
    assert not owned.state.is_default and owned.state.parse_status == "failed"
    with pytest.raises(resumes.ResumeArtifactNotReadyError):
        resumes.read_resume_text(owned)


def test_http_workspace_commands_and_invalid_import_are_atomic():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.security import get_current_user
    from app.db.database import get_db, Base
    from app.models.user import User
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    # HTTP commands commit and roll back whole transactions. Give this test its
    # own database rather than releasing SQLite savepoints in the suite fixture.
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="http_owner", hashed_password="test-only", is_active=True)
    db.add(user)
    db.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db
    try:
        # Base metadata owns this isolated test schema; no production lifespan.
        client = TestClient(app, raise_server_exceptions=True)
        assert (
            client.get(
                "/api/v1/career-workspace/jobs",
                params={"q": "", "offset": 0, "limit": 30},
            ).status_code
            == 200
        )
        result = client.post(
            "/api/v1/career-workspace/jobs",
            json={
                "operation_key": "http-job",
                "company_name": "HTTP公司",
                "job_title": "工程师",
                "description": "无需链接的岗位描述",
            },
        )
        assert result.status_code == 201, result.text
        result = result.json()
        response = client.post(
            f"/api/v1/career-workspace/jobs/{result['id']}/stage",
            json={
                "expected_version": result["version"],
                "stage": "applied",
                "operation_key": "bad-submission",
                "occurred_at": utc_now().isoformat(),
                "version_ids": ["missing"],
            },
        )
        assert response.status_code == 404
        assert (
            client.get(f"/api/v1/career-workspace/jobs/{result['id']}").json()["stage"]
            == "saved"
        )
        before = workspace.list_jobs(db, user.id)["total"]
        response = client.post(
            "/api/v1/career-workspace/import",
            json=[
                {
                    "operation_key": "good-import",
                    "company_name": "公司A",
                    "job_title": "工程师",
                },
                {
                    "operation_key": "bad-import",
                    "company_name": "公司B",
                    "job_title": "工程师",
                    "source_url": "javascript:bad",
                },
            ],
        )
        assert response.status_code == 422
        assert workspace.list_jobs(db, user.id)["total"] == before
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()
