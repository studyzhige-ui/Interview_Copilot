"""ANA-7: reanalyze_record — reset semantics, guards, dispatch rollback."""
from __future__ import annotations

import pytest

from app.models.interview_record import InterviewRecord
from app.services.interview import record_admin


@pytest.fixture(autouse=True)
def _seed_user(db_session):
    from app.models.user import User

    db_session.add(User(username="alice", hashed_password="x"))
    db_session.flush()


def _pk(db):
    from app.models.user import User

    return db.query(User.id).filter(User.username == "alice").scalar()




def _mk_record(db, rid, *, source="upload", status="failed", **kw):
    rec = InterviewRecord(
        id=rid, user_id=_pk(db), source=source, status=status, **kw,
    )
    db.add(rec)
    db.commit()
    return rec


def test_reanalyze_resets_and_dispatches(db_session, monkeypatch):
    from types import SimpleNamespace

    rec = _mk_record(
        db_session, "ir_re1", status="failed",
        analysis_json='{"overall": {}}', error_message="boom",
        debrief_summary="旧摘要", analyzed_qa_count=7,
    )
    monkeypatch.setattr(
        record_admin, "process_interview_analysis",
        SimpleNamespace(delay=lambda rid: SimpleNamespace(id="task-9")),
        raising=False,
    )
    import app.worker.tasks as wt

    monkeypatch.setattr(
        wt, "process_interview_analysis",
        SimpleNamespace(delay=lambda rid: SimpleNamespace(id="task-9")),
    )

    task = record_admin.reanalyze_record(db_session, rec)

    db_session.refresh(rec)
    assert task.id == "task-9"
    assert rec.status == "pending"
    assert rec.analysis_json is None
    assert rec.error_message is None
    assert rec.debrief_summary is None      # regenerates from the new report
    assert rec.analyzed_qa_count == 0
    assert rec.celery_task_id == "task-9"


def test_reanalyze_rejects_mock_and_inflight(db_session):
    mock_rec = _mk_record(db_session, "ir_re2", source="mock", status="review_failed")
    with pytest.raises(record_admin.ReanalyzeNotAllowed):
        record_admin.reanalyze_record(db_session, mock_rec)

    running = _mk_record(db_session, "ir_re3", status="analyzing")
    with pytest.raises(record_admin.ReanalyzeNotAllowed):
        record_admin.reanalyze_record(db_session, running)


def test_reanalyze_dispatch_failure_rolls_back_to_failed(db_session, monkeypatch):
    from types import SimpleNamespace

    rec = _mk_record(db_session, "ir_re4", status="completed")
    import app.worker.tasks as wt

    def _raise(rid):
        raise ConnectionError("broker down")

    monkeypatch.setattr(
        wt, "process_interview_analysis", SimpleNamespace(delay=_raise),
    )
    with pytest.raises(ConnectionError):
        record_admin.reanalyze_record(db_session, rec)
    db_session.refresh(rec)
    assert rec.status == "failed"
    assert "派发失败" in (rec.error_message or "")


# ── ANA-3: orchestrator stage-gate shell loader ──────────────────────────


def test_load_existing_qa_shells_roundtrip(db_session, monkeypatch):
    from app.models.interview_qa import InterviewQA
    # The package __init__ re-exports the singleton under the module's own
    # name, so ``import ... as orch`` binds the INSTANCE — go via sys.modules.
    import sys

    import app.services.interview.analysis_orchestrator  # noqa: F401
    orch = sys.modules["app.services.interview.analysis_orchestrator"]

    rec = _mk_record(db_session, "ir_gate1", status="analyzing")
    db_session.add_all([
        InterviewQA(record_id=rec.id, order_idx=0, question="Q1", answer="A1",
                    phase="self_intro"),
        InterviewQA(record_id=rec.id, order_idx=1, question="Q2", answer="A2",
                    phase="technical"),
        InterviewQA(record_id=rec.id, order_idx=2, question="  ", answer="x",
                    phase="general"),  # blank question — skipped
    ])
    db_session.commit()

    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            self._inner.commit()

    monkeypatch.setattr(orch, "SessionLocal", lambda: _NoClose(db_session))
    pairs = orch.analysis_orchestrator._load_existing_qa_shells(rec.id)

    assert [p["question"] for p in pairs] == ["Q1", "Q2"]
    assert pairs[0]["index"] == 1 and pairs[1]["index"] == 2
    assert pairs[1]["phase"] == "technical"


def test_load_existing_qa_shells_empty_for_fresh_record(db_session, monkeypatch):
    # The package __init__ re-exports the singleton under the module's own
    # name, so ``import ... as orch`` binds the INSTANCE — go via sys.modules.
    import sys

    import app.services.interview.analysis_orchestrator  # noqa: F401
    orch = sys.modules["app.services.interview.analysis_orchestrator"]

    rec = _mk_record(db_session, "ir_gate2", status="pending")

    class _NoClose:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def close(self):
            self._inner.commit()

    monkeypatch.setattr(orch, "SessionLocal", lambda: _NoClose(db_session))
    assert orch.analysis_orchestrator._load_existing_qa_shells(rec.id) == []
