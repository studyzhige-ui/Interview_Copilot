"""Canonical-only resume worker regression tests."""


def test_legacy_resume_reindex_job_is_outside_every_production_lane():
    from app.services.outbox import CLEANUP_JOB_TYPES, INDEX_JOB_TYPES

    retired = "milvus_reindex_resume"
    assert retired not in INDEX_JOB_TYPES
    assert retired not in CLEANUP_JOB_TYPES


def test_pre_cutover_resume_task_terminates_without_legacy_write(
    db_session,
    monkeypatch,
):
    from app.models.resume import Resume
    from app.models.user import User
    from app.worker.tasks import resume as resume_tasks

    user = User(username="retired-resume-worker", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    legacy = Resume(
        id="rsm_retired_worker",
        user_id=user.id,
        title="Legacy CV",
        is_default=True,
        parse_status="pending",
        parse_error="keep exact legacy state",
    )
    db_session.add(legacy)
    db_session.commit()

    class _SessionContext:
        def __enter__(self):
            return db_session

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(resume_tasks, "SessionLocal", _SessionContext)

    result = resume_tasks.process_resume_parse.run(legacy.id)

    db_session.refresh(legacy)
    assert result == {
        "status": "retired_legacy_resume",
        "resume_id": legacy.id,
    }
    assert legacy.parse_status == "pending"
    assert legacy.parse_error == "keep exact legacy state"
