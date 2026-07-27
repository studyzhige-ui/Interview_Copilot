from app.models.outbox_job import OutboxJob
from app.models.resume import Resume
from app.models.resume_section import ResumeSection
from app.models.user import User
from app.services.resume import resume_outbox
from app.services.uploads.outbox_service import run_due_outbox_jobs


def _seed(db):
    user = User(username="resume-outbox", hashed_password="x")
    db.add(user)
    db.commit()
    resume = Resume(
        id="rsm_outbox",
        user_id=user.id,
        title="CV",
        is_default=True,
        parse_status="processing",
    )
    section = ResumeSection(
        id="rs_outbox",
        user_id=user.id,
        resume_id=resume.id,
        section_type="skill",
        title="Skills",
        content="Python",
        order_idx=0,
    )
    db.add_all([resume, section])
    resume_outbox.enqueue_resume_reindex(
        db,
        user_pk=user.id,
        resume_id=resume.id,
    )
    db.commit()
    return resume, section


def test_resume_reindex_graduates_resume_to_ready(db_session, monkeypatch):
    resume, section = _seed(db_session)
    calls: list[str] = []

    from app.services.resume import resume_vector_service as vectors

    monkeypatch.setattr(
        vectors.resume_vector_service,
        "delete_by_resume",
        lambda resume_id: calls.append(f"delete:{resume_id}"),
    )

    def upsert(row, db=None):
        calls.append(f"upsert:{row.id}")
        row.embedding_status = "ready"

    monkeypatch.setattr(vectors.resume_vector_service, "upsert_section", upsert)

    assert run_due_outbox_jobs(db_session) == 1
    db_session.refresh(resume)
    db_session.refresh(section)
    assert resume.parse_status == "ready"
    assert section.embedding_status == "ready"
    assert calls == ["delete:rsm_outbox", "upsert:rs_outbox"]


def test_archived_resume_job_only_deletes_stale_index(db_session, monkeypatch):
    resume, _section = _seed(db_session)
    resume.archived_at = resume.created_at
    db_session.commit()
    calls: list[str] = []

    from app.services.resume import resume_vector_service as vectors

    monkeypatch.setattr(
        vectors.resume_vector_service,
        "delete_by_resume",
        lambda resume_id: calls.append(resume_id),
    )
    monkeypatch.setattr(
        vectors.resume_vector_service,
        "upsert_section",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("archived resume must not be reinserted")
        ),
    )

    assert run_due_outbox_jobs(db_session) == 1
    assert calls == ["rsm_outbox"]
    job = db_session.query(OutboxJob).filter(OutboxJob.aggregate_id == resume.id).one()
    assert job.status == "succeeded"
