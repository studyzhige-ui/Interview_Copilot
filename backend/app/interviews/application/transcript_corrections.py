"""Owned, idempotent transcript edits. Source changes never call a model."""

from __future__ import annotations

import hashlib
import json
import uuid
from sqlalchemy import and_, or_
from app.core.command_errors import CommandError
from app.db.types import utc_now
from app.models.interview_record import InterviewRecord
from app.models.interview_transcript import InterviewTranscript, _generate_transcript_id
from app.models.interview_qa import InterviewQA
from app.models.transcript_correction import TranscriptCorrection
from app.media.application.transcript_evidence import (
    TranscriptEvidence,
    group_acoustic_turns,
    render_raw_turns,
)
from app.interviews.application.review_fence import lock_record
from app.interviews.application.review_invalidation import invalidate_review


def _owned(db, record_id, user_pk, *, lock=False):
    record = lock_record(db, record_id) if lock else db.get(InterviewRecord, record_id)
    if record is None or record.user_id != user_pk:
        raise CommandError("not_found", "面试记录不存在")
    return record


def confirmed_roles(db, transcript_id):
    receipt = (
        db.query(TranscriptCorrection).filter_by(transcript_id=transcript_id).first()
    )
    return dict(receipt.confirmed_roles_json) if receipt else {}


def _receipt(row, record):
    return dict(
        request_id=row.request_id,
        previous_transcript_id=row.previous_transcript_id,
        transcript_id=row.transcript_id,
        current_transcript_id=record.transcript_id,
        review_generation=row.review_generation,
        created_at=row.created_at.isoformat(),
        reanalysis_required=record.status not in {"completed", "review_ready"},
    )


def get_receipt(db, *, record_id, user_pk, request_id):
    record = _owned(db, record_id, user_pk)
    row = (
        db.query(TranscriptCorrection)
        .filter_by(record_id=record_id, request_id=request_id)
        .first()
    )
    if row is None:
        raise CommandError("not_found", "未找到该纠正请求的收据")
    return _receipt(row, record)


def corrected_evidence(evidence, command):
    payload = evidence.model_dump(mode="json")
    words = {w["word_id"]: w for w in payload["words"]}
    speakers = {w.speaker_id for w in evidence.words if w.speaker_id}
    if set(command.speaker_roles) - speakers:
        raise CommandError("invalid", "角色标注引用了不存在的说话人")
    for edit in command.words:
        if edit.word_id not in words:
            raise CommandError("invalid", "纠正引用了不存在的词")
        target = words[edit.word_id]
        if edit.text is not None and edit.text != target["text"]:
            target["text"] = edit.text
            target["asr_confidence"] = None
            # A manually changed token did not pass through a forced aligner.
            if target["start"] is not None:
                target["alignment_status"] = "estimated"
        if "speaker_id" in edit.model_fields_set:
            if edit.speaker_id is not None and edit.speaker_id not in speakers:
                raise CommandError("invalid", "不能创建未经录音支持的说话人编号")
            target["speaker_id"] = edit.speaker_id
            target["speaker_confidence"] = None
    from app.media.application.transcript_evidence import EvidenceWord

    parsed = [EvidenceWord.model_validate(w) for w in payload["words"]]
    payload["acoustic_turns"] = [t.model_dump() for t in group_acoustic_turns(parsed)]
    return TranscriptEvidence.model_validate(payload)


def correct_transcript(db, *, record_id, user_pk, command):
    record = _owned(db, record_id, user_pk, lock=True)
    data = command.model_dump(mode="json", exclude_unset=True)
    digest = hashlib.sha256(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    prior = (
        db.query(TranscriptCorrection)
        .filter_by(record_id=record_id, request_id=command.request_id)
        .first()
    )
    if prior:
        if prior.command_sha256 != digest:
            raise CommandError("conflict", "同一请求编号不能用于不同的修改内容")
        return _receipt(prior, record)
    if record.source != "upload":
        raise CommandError("conflict", "此入口仅纠正上传录音；模拟面试请修改对应回答")
    if record.transcript_id != command.expected_transcript_id:
        raise CommandError(
            "conflict", "转写版本已改变，请核对最新内容；你的草稿未被覆盖"
        )
    before = (
        db.query(InterviewTranscript)
        .filter_by(id=record.transcript_id, record_id=record_id, user_id=user_pk)
        .first()
    )
    if before is None or not before.evidence_json:
        raise CommandError("conflict", "此记录尚无可纠正的词级证据")
    evidence = TranscriptEvidence.model_validate(before.evidence_json)
    updated = corrected_evidence(evidence, command)
    old_roles = confirmed_roles(db, before.id)
    speakers = {w.speaker_id for w in updated.words if w.speaker_id}
    roles = {
        k: v for k, v in {**old_roles, **command.speaker_roles}.items() if k in speakers
    }
    if updated == evidence and roles == old_roles:
        raise CommandError("invalid", "没有需要保存的更改")
    rows = (
        db.query(InterviewQA)
        .filter_by(record_id=record_id)
        .order_by(InterviewQA.order_idx)
        .with_for_update()
        .all()
    )
    archived = invalidate_review(
        db,
        record,
        rows,
        message="转写或角色已纠正，旧问答和评分已失效。请明确重新分析；不会自动调用模型。",
    )
    after = InterviewTranscript(
        id=_generate_transcript_id(),
        record_id=record_id,
        user_id=user_pk,
        provider=before.provider,
        language=updated.language,
        text=render_raw_turns(updated),
        evidence_schema_version=updated.schema_version,
        evidence_json=updated.model_dump(mode="json"),
        duration_seconds=updated.audio.duration_seconds,
        status="ready",
    )
    db.add(after)
    db.flush()
    record.transcript_id = after.id
    # Current QA projection is rebuilt explicitly. Archive all source text and
    # provenance above; existing QA correction receipts intentionally use soft IDs.
    db.query(InterviewQA).filter_by(record_id=record_id).delete(
        synchronize_session="fetch"
    )
    receipt = TranscriptCorrection(
        id=str(uuid.uuid4()),
        record_id=record_id,
        author_id=user_pk,
        request_id=command.request_id,
        previous_transcript_id=before.id,
        transcript_id=after.id,
        command_sha256=digest,
        command_json=data,
        confirmed_roles_json=roles,
        invalidated_review_json=archived,
        review_generation=record.review_generation,
        created_at=utc_now(),
    )
    db.add(receipt)
    db.flush()
    result = _receipt(receipt, record)
    db.commit()
    return result


def get_page(db, *, record_id, user_pk, transcript_id=None, offset=0, limit=100):
    if not 0 <= offset or not 1 <= limit <= 200:
        raise CommandError("invalid", "invalid transcript page")
    record = _owned(db, record_id, user_pk)
    tr = (
        db.query(InterviewTranscript)
        .filter_by(
            id=transcript_id or record.transcript_id,
            record_id=record_id,
            user_id=user_pk,
        )
        .first()
    )
    if tr is None or not tr.evidence_json:
        raise CommandError("not_found", "尚无词级转写证据")
    evidence = TranscriptEvidence.model_validate(tr.evidence_json)
    suggestions = {
        x["speaker_id"]: x["role"]
        for x in (tr.structure_json or {}).get("speaker_roles", [])
        if x.get("role") in {"candidate", "interviewer", "unknown"}
    }
    return dict(
        transcript_id=tr.id,
        current_transcript_id=record.transcript_id,
        source=tr.provider or "unknown",
        language=tr.language,
        audio_file_asset_id=evidence.audio.file_asset_id,
        duration_seconds=evidence.audio.duration_seconds,
        word_count=len(evidence.words),
        words=[
            w.model_dump(
                include={
                    "word_id",
                    "text",
                    "start",
                    "end",
                    "alignment_status",
                    "speaker_id",
                    "overlap",
                }
            )
            for w in evidence.words[offset : offset + limit]
        ],
        speakers=sorted({w.speaker_id for w in evidence.words if w.speaker_id}),
        confirmed_roles=confirmed_roles(db, tr.id),
        suggested_roles=suggestions,
        next_offset=offset + limit if offset + limit < len(evidence.words) else None,
    )


def history(db, *, record_id, user_pk, before=None, limit=20):
    _owned(db, record_id, user_pk)
    if not 1 <= limit <= 50:
        raise CommandError("invalid", "invalid history page size")
    query = db.query(TranscriptCorrection).filter_by(record_id=record_id)
    if before:
        anchor = query.filter_by(request_id=before).first()
        if anchor is None:
            raise CommandError("invalid", "invalid history cursor")
        query = query.filter(
            or_(
                TranscriptCorrection.created_at < anchor.created_at,
                and_(
                    TranscriptCorrection.created_at == anchor.created_at,
                    TranscriptCorrection.request_id < anchor.request_id,
                ),
            )
        )
    rows = (
        query.order_by(
            TranscriptCorrection.created_at.desc(),
            TranscriptCorrection.request_id.desc(),
        )
        .limit(limit + 1)
        .all()
    )
    return dict(
        items=[
            dict(
                request_id=r.request_id,
                previous_transcript_id=r.previous_transcript_id,
                transcript_id=r.transcript_id,
                reason=r.command_json["reason"],
                word_ids=[w["word_id"] for w in r.command_json.get("words", [])],
                confirmed_roles=r.confirmed_roles_json,
                created_at=r.created_at.isoformat(),
            )
            for r in rows[:limit]
        ],
        next_cursor=rows[limit - 1].request_id if len(rows) > limit else None,
    )
