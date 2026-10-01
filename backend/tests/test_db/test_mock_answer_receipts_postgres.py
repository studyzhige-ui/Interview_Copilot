"""Real PostgreSQL request races: no second dispatch and receipts outlive runtime."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from sqlalchemy import text

from app.interviews.application import mock_flow, mock_answer_receipts as receipts
from app.models.interview_record import InterviewRecord
from app.models.mock_interview_runtime import MockInterviewRuntime
from app.models.mock_answer_submission import MockAnswerSubmission
from app.models.user import User
from tests.test_services.interview.test_mock_flow_phase5 import _make_run, _stub_turn


def test_two_sessions_same_intent_dispatch_once_and_replay_committed_result(
    database, monkeypatch
):
    _, _, factory = database
    with factory() as db:
        db.add(User(username="alice", hashed_password="x"))
        db.flush()
        record, runtime, _ = _make_run(db)
        rid, qid = record.id, runtime.current_question_message_id
    _stub_turn(monkeypatch)
    generate = mock_flow.mock_interview_service.generate_next_turn
    entered, release = Event(), Event()
    calls = []

    async def held(**kwargs):
        calls.append(1)
        entered.set()
        assert await asyncio.to_thread(release.wait, 10), "test model was not released"
        return await generate(**kwargs)

    monkeypatch.setattr(mock_flow.mock_interview_service, "generate_next_turn", held)
    args = dict(
        request_id=str(uuid4()),
        question_message_id=qid,
        answer_text="same",
        answer_audio_file_asset_id=None,
    )

    def attempt():
        with factory() as db:
            try:
                return asyncio.run(
                    mock_flow.submit_answer(
                        db,
                        record=db.get(InterviewRecord, rid),
                        runtime=db.get(MockInterviewRuntime, rid),
                        **args,
                    )
                )
            except receipts.AnswerRequestUnresolved:
                db.rollback()
                return "unresolved"

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(attempt)
        try:
            assert entered.wait(10)
            assert workers.submit(attempt).result(timeout=10) == "unresolved"
            with factory() as reader:
                assert (
                    receipts.read_receipt(reader, rid, args["request_id"]).status
                    == "in_progress"
                )
        finally:
            release.set()
        result = first.result(timeout=10)
    assert attempt() == result and len(calls) == 1
    with factory() as db:
        assert db.query(MockAnswerSubmission).count() == 1
        # Keep the receipt after the ephemeral runtime ends, then cascade it with
        # source record deletion; no answer-bearing orphan survives the record.
        db.delete(db.get(MockInterviewRuntime, rid))
        db.commit()
        assert receipts.read_receipt(db, rid, args["request_id"]).status == "completed"
        db.execute(text("DELETE FROM interview_records WHERE id=:rid"), {"rid": rid})
        db.commit()
        assert db.query(MockAnswerSubmission).count() == 0
