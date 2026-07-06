"""Zombie-state sweeper (ANA-9): stale in-flight records get a terminal state.

Uses the same local-SQLite idiom as tests/test_services/interview — the
sweeper opens its own SessionLocal, so we monkeypatch the module's.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def sweeper_db(monkeypatch):
    import app.models.interview_qa  # noqa: F401
    import app.models.interview_record  # noqa: F401
    import app.models.interview_transcript  # noqa: F401
    import app.models.user  # noqa: F401
    from app.db.database import Base
    from app.models.user import User
    from app.worker.tasks import maintenance

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Base.metadata.tables["users"],
            Base.metadata.tables["interview_records"],
            Base.metadata.tables["interview_qa"],
            Base.metadata.tables["interview_transcripts"],
        ],
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    session.add(User(username="alice", hashed_password="x"))
    session.commit()

    class _NoCloseSession:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            self._inner.commit()

        # ``with SessionLocal() as db`` in the sweeper.
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

    monkeypatch.setattr(maintenance, "SessionLocal", lambda: _NoCloseSession(session))
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _record(db, *, source: str, status: str, age: timedelta):
    from app.models.interview_record import InterviewRecord
    from app.models.user import User

    pk = db.query(User.id).filter(User.username == "alice").scalar()
    rec = InterviewRecord(
        id=f"ir_{source}_{status}_{int(age.total_seconds())}",
        user_id=pk,
        source=source,
        status=status,
        updated_at=datetime.utcnow() - age,
    )
    db.add(rec)
    db.commit()
    return rec


def test_stale_upload_record_swept_to_failed(sweeper_db):
    from app.worker.tasks import maintenance

    rec = _record(sweeper_db, source="upload", status="analyzing", age=timedelta(hours=3))
    result = maintenance.sweep_stale_interview_records.run()

    sweeper_db.refresh(rec)
    assert result == {"swept": 1}
    assert rec.status == "failed"
    assert rec.error_message


def test_stale_mock_review_swept_to_review_failed_after_30min(sweeper_db):
    from app.worker.tasks import maintenance

    rec = _record(sweeper_db, source="mock", status="processing_review", age=timedelta(minutes=45))
    result = maintenance.sweep_stale_interview_records.run()

    sweeper_db.refresh(rec)
    assert result == {"swept": 1}
    assert rec.status == "review_failed"


def test_fresh_inflight_records_not_swept(sweeper_db):
    from app.worker.tasks import maintenance

    upload = _record(sweeper_db, source="upload", status="transcribing", age=timedelta(hours=1))
    review = _record(sweeper_db, source="mock", status="processing_review", age=timedelta(minutes=10))
    result = maintenance.sweep_stale_interview_records.run()

    sweeper_db.refresh(upload)
    sweeper_db.refresh(review)
    assert result == {"swept": 0}
    assert upload.status == "transcribing"
    assert review.status == "processing_review"


def test_terminal_and_mock_in_progress_records_untouched(sweeper_db):
    from app.worker.tasks import maintenance

    done = _record(sweeper_db, source="upload", status="completed", age=timedelta(days=2))
    live = _record(sweeper_db, source="mock", status="mock_in_progress", age=timedelta(days=2))
    result = maintenance.sweep_stale_interview_records.run()

    sweeper_db.refresh(done)
    sweeper_db.refresh(live)
    assert result == {"swept": 0}
    assert done.status == "completed"
    # An abandoned mock_in_progress run is the resume banner's business
    # (and the abandon endpoint's), not the sweeper's.
    assert live.status == "mock_in_progress"


# ── UP-3: orphan file-asset sweeper ─────────────────────────────────────


class _CtxSession:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        self._inner.commit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def orphan_db(db_session, monkeypatch):
    from app.models.user import User
    from app.worker.tasks import maintenance

    db_session.add(User(username="alice", hashed_password="x"))
    db_session.commit()
    monkeypatch.setattr(maintenance, "SessionLocal", lambda: _CtxSession(db_session))
    return db_session


def _asset(db, *, status: str, age: timedelta):
    from app.models.file_asset import FileAsset
    from app.models.user import User

    pk = db.query(User.id).filter(User.username == "alice").scalar()
    asset = FileAsset(
        id=f"fa_{status}_{int(age.total_seconds())}",
        user_id=pk,
        purpose="resume",
        original_filename="cv.pdf",
        object_key=f"k/{status}/{int(age.total_seconds())}.pdf",
        storage_uri=f"s3://b/k/{status}/{int(age.total_seconds())}.pdf",
        upload_status=status,
        updated_at=datetime.utcnow() - age,
    )
    db.add(asset)
    db.commit()
    return asset


def test_orphan_pending_upload_swept_with_blob_cleanup(orphan_db):
    from app.models.outbox_job import OutboxJob
    from app.worker.tasks import maintenance

    asset = _asset(orphan_db, status="pending_upload", age=timedelta(hours=30))
    result = maintenance.sweep_orphan_file_assets.run()

    orphan_db.refresh(asset)
    assert result == {"swept": 1}
    assert asset.upload_status == "deleted"
    assert asset.deleted_at is not None
    job = orphan_db.query(OutboxJob).filter(
        OutboxJob.job_type == "delete_object",
        OutboxJob.aggregate_id == asset.id,
    ).first()
    assert job is not None


def test_orphan_failed_row_marked_deleted_without_second_enqueue(orphan_db):
    from app.models.outbox_job import OutboxJob
    from app.worker.tasks import maintenance

    asset = _asset(orphan_db, status="failed", age=timedelta(hours=30))
    result = maintenance.sweep_orphan_file_assets.run()

    orphan_db.refresh(asset)
    assert result == {"swept": 1}
    assert asset.upload_status == "deleted"
    # cleanup was _fail_asset's job at failure time — the sweeper must not
    # queue a duplicate delete_object job for a failed asset.
    jobs = orphan_db.query(OutboxJob).filter(
        OutboxJob.aggregate_id == asset.id,
    ).all()
    assert jobs == []


def test_fresh_and_live_assets_not_swept(orphan_db):
    from app.worker.tasks import maintenance

    fresh = _asset(orphan_db, status="pending_upload", age=timedelta(hours=1))
    live = _asset(orphan_db, status="consumed", age=timedelta(days=30))
    result = maintenance.sweep_orphan_file_assets.run()

    orphan_db.refresh(fresh)
    orphan_db.refresh(live)
    assert result == {"swept": 0}
    assert fresh.upload_status == "pending_upload"
    assert live.upload_status == "consumed"
