"""No models: source editing, replay and stale-publication contracts."""

import uuid
import pytest
from pydantic import ValidationError
from app.models.user import User
from app.models.interview_record import InterviewRecord
from app.models.interview_qa import InterviewQA
from app.models.interview_transcript import InterviewTranscript
from app.models.transcript_correction import TranscriptCorrection
from app.schemas.transcript_correction import TranscriptCorrectionRequest
from app.core.command_errors import CommandError
from app.interviews.application import transcript_corrections as service
from app.interviews.application.review_fence import (
    lock_record,
    review_scope,
    ReviewSuperseded,
)
from tests.test_services.voice.test_transcript_evidence import _evidence


def seed(db):
    owner = User(username="transcript-owner", hashed_password="x")
    stranger = User(username="transcript-stranger", hashed_password="x")
    db.add_all([owner, stranger])
    db.flush()
    record = InterviewRecord(
        user_id=owner.id,
        source="upload",
        status="completed",
        analysis_json='{"overall":{"score":8}}',
    )
    db.add(record)
    db.flush()
    evidence = _evidence()
    tr = InterviewTranscript(
        record_id=record.id,
        user_id=owner.id,
        provider="fixture",
        status="ready",
        evidence_schema_version=2,
        evidence_json=evidence.model_dump(mode="json"),
        text="original",
        duration_seconds=3,
    )
    db.add(tr)
    db.flush()
    record.transcript_id = tr.id
    qa = InterviewQA(
        record_id=record.id,
        order_idx=0,
        question="旧问题",
        answer="旧回答",
        score=8,
        source_transcript_id=tr.id,
        source_provenance_json={"words": ["w000004"]},
    )
    db.add(qa)
    db.commit()
    return owner, stranger, record, tr, qa


@pytest.fixture
def data(db_session):
    return seed(db_session)


def command(tr, **kwargs):
    values = dict(
        request_id=str(uuid.uuid4()),
        expected_transcript_id=tr.id,
        reason="核对原录音",
        words=[{"word_id": "w000004", "text": "维护"}],
    )
    values.update(kwargs)
    return TranscriptCorrectionRequest.model_validate(values)


def test_edit_preserves_old_evidence_and_invalidates_derived_data(db_session, data):
    owner, _, record, tr, qa = data
    original = dict(tr.evidence_json)
    receipt = service.correct_transcript(
        db_session, record_id=record.id, user_pk=owner.id, command=command(tr)
    )
    assert receipt["transcript_id"] != tr.id
    assert db_session.get(InterviewTranscript, tr.id).evidence_json == original
    current = service.get_page(db_session, record_id=record.id, user_pk=owner.id)
    word = current["words"][3]
    assert (word["text"], word["alignment_status"]) == ("维护", "estimated")
    assert record.analysis_json is None and record.status == "failed"
    assert db_session.query(InterviewQA).filter_by(record_id=record.id).count() == 0
    saved = db_session.query(TranscriptCorrection).one()
    assert saved.invalidated_review_json["questions"][0]["answer"] == "旧回答"
    assert saved.invalidated_review_json["questions"][0]["score"] == 8
    old = service.get_page(
        db_session, record_id=record.id, user_pk=owner.id, transcript_id=tr.id
    )
    assert old["words"][3]["text"] == "负责"


def test_lost_response_replays_exact_receipt_not_a_second_correction(db_session, data):
    owner, _, record, tr, _ = data
    cmd = command(tr)
    first = service.correct_transcript(
        db_session, record_id=record.id, user_pk=owner.id, command=cmd
    )
    second = service.correct_transcript(
        db_session, record_id=record.id, user_pk=owner.id, command=cmd
    )
    assert first == second
    assert db_session.query(TranscriptCorrection).count() == 1
    changed = cmd.model_copy(update={"reason": "另一意图"})
    with pytest.raises(CommandError, match="请求编号"):
        service.correct_transcript(
            db_session, record_id=record.id, user_pk=owner.id, command=changed
        )


def test_stale_editor_and_old_worker_cannot_publish(db_session, data):
    owner, _, record, tr, _ = data
    old = record.review_generation
    service.correct_transcript(
        db_session, record_id=record.id, user_pk=owner.id, command=command(tr)
    )
    with pytest.raises(CommandError, match="版本已改变"):
        service.correct_transcript(
            db_session, record_id=record.id, user_pk=owner.id, command=command(tr)
        )
    with review_scope(record.id, old), pytest.raises(ReviewSuperseded):
        lock_record(db_session, record.id)


def test_owner_scope_applies_to_history_receipts_and_old_versions(db_session, data):
    owner, stranger, record, tr, _ = data
    cmd = command(tr)
    service.correct_transcript(
        db_session, record_id=record.id, user_pk=owner.id, command=cmd
    )
    for operation, args in [
        (service.get_page, {}),
        (service.history, {}),
        (service.get_receipt, {"request_id": cmd.request_id}),
        (service.correct_transcript, {"command": command(tr)}),
    ]:
        with pytest.raises(CommandError) as exc:
            operation(db_session, record_id=record.id, user_pk=stranger.id, **args)
        assert exc.value.kind == "not_found"


def test_role_only_edit_keeps_original_times_and_words(db_session, data):
    owner, _, record, tr, _ = data
    roles = {"SPEAKER_01": "candidate", "SPEAKER_00": "interviewer"}
    service.correct_transcript(
        db_session,
        record_id=record.id,
        user_pk=owner.id,
        command=command(tr, words=[], speaker_roles=roles),
    )
    current = service.get_page(
        db_session, record_id=record.id, user_pk=owner.id, limit=2
    )
    assert current["confirmed_roles"] == roles and current["next_offset"] == 2
    assert current["words"][1]["alignment_status"] == "aligned"
    assert (
        service.history(db_session, record_id=record.id, user_pk=owner.id)["items"][0][
            "confirmed_roles"
        ]
        == roles
    )


@pytest.mark.parametrize(
    "edits",
    [
        [{"word_id": "w999999", "text": "错"}],
        [{"word_id": "w000001", "speaker_id": "invented"}],
    ],
)
def test_unknown_source_identity_rejected_atomically(db_session, data, edits):
    owner, _, record, tr, _ = data
    with pytest.raises(CommandError):
        service.correct_transcript(
            db_session,
            record_id=record.id,
            user_pk=owner.id,
            command=command(tr, words=edits),
        )
    assert record.transcript_id == tr.id and record.analysis_json
    assert db_session.query(TranscriptCorrection).count() == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"words": [{"word_id": "w000001"}]},
        {"words": [{"word_id": "w000001", "text": None}]},
        {"words": [{"word_id": "w000001", "text": " "}]},
        {"words": [{"word_id": "w000001", "text": "x"}] * 2},
        {"request_id": "bad"},
        {"words": [], "speaker_roles": {}},
        {"reason": " "},
    ],
)
def test_invalid_command_is_not_normalized_into_success(data, patch):
    with pytest.raises(ValidationError):
        command(data[3], **patch)


@pytest.mark.asyncio
async def test_confirmed_roles_are_not_overwritten_by_llm(monkeypatch):
    from app.interviews.application import transcript_structure_service as structure

    evidence = _evidence()

    async def fail(*args, **kwargs):
        raise AssertionError("must not infer already confirmed roles")

    monkeypatch.setattr(structure, "_infer_roles", fail)
    observed = []

    async def utterances(ev, roles, llm):
        observed.extend(roles)
        raise RuntimeError("stop_after_roles")

    monkeypatch.setattr(structure, "_project_utterances", utterances)
    with pytest.raises(RuntimeError, match="stop_after_roles"):
        await structure.project_interview_qa(
            evidence,
            llm=object(),
            confirmed_roles={"SPEAKER_01": "candidate", "SPEAKER_00": "interviewer"},
        )
    assert all(role.source == "user" and role.confidence is None for role in observed)
