"""Load once and render the interview context used by debrief conversations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.services.interview.analysis_context import (
    build_question_index,
    build_report_context,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InterviewQuestionReference:
    order_idx: int
    phase: str
    question: str
    answer: str
    score: float | None
    critique: str
    improved_answer: str
    tags: tuple[str, ...]

    @property
    def index(self) -> int:
        return self.order_idx + 1


@dataclass(frozen=True)
class InterviewReference:
    record_id: str
    title: str
    tag: str
    source: str
    status: str
    analysis_json: str | None
    resume_text: str
    audio_file_asset_id: str | None
    resume_id: str | None
    resume_file_asset_id: str | None
    jd_file_asset_id: str | None
    questions: tuple[InterviewQuestionReference, ...]

    @property
    def question_catalog(self) -> list[tuple[int, str]]:
        return [(question.index, question.question) for question in self.questions]


def load_interview_reference(
    interview_id: str,
    owner_pk: int,
) -> InterviewReference | None:
    """Load one owner-scoped record and all QA rows in two queries."""
    db: Session = SessionLocal()
    try:
        record = (
            db.query(InterviewRecord)
            .filter(
                InterviewRecord.id == interview_id,
                InterviewRecord.user_id == owner_pk,
            )
            .first()
        )
        if record is None:
            return None
        qa_rows = (
            db.query(InterviewQA)
            .filter(InterviewQA.record_id == interview_id)
            .order_by(InterviewQA.order_idx)
            .all()
        )
        return InterviewReference(
            record_id=record.id,
            title=record.title or "未命名",
            tag=record.tag or "",
            source=record.source or "",
            status=record.status or "",
            analysis_json=record.analysis_json,
            resume_text=(record.resume_text_snapshot or "").strip(),
            audio_file_asset_id=record.audio_file_asset_id,
            resume_id=record.resume_id,
            resume_file_asset_id=record.resume_file_asset_id,
            jd_file_asset_id=record.jd_file_asset_id,
            questions=tuple(_question_from_row(row) for row in qa_rows),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_interview_reference failed for %s: %s", interview_id, exc)
        return None
    finally:
        db.close()


def render_interview_reference(
    reference: InterviewReference,
    question_indexes: tuple[int, ...] | list[int] = (),
) -> str:
    """Render overview plus full details for every explicitly selected index.

    There is deliberately no item-count limit. The shared context pipeline
    applies its token budget after rendering, with focused details placed first
    so an oversized resume or report cannot displace the requested evidence.
    """
    meta = [f"record_id: {reference.record_id}"]
    if reference.tag:
        meta.append(f"标签: {reference.tag}")
    if reference.source:
        meta.append(f"来源: {reference.source}")
    if reference.status:
        meta.append(f"状态: {reference.status}")
    sections = [
        f"# 当前复盘的面试: {reference.title}\n" + " · ".join(meta),
        _render_question_details(reference.questions, question_indexes),
        build_report_context(reference.analysis_json),
        build_question_index(reference.questions),
    ]

    if reference.resume_text:
        sections.append(f"## 候选人简历全文\n{reference.resume_text}")

    uploads = _render_uploads(reference)
    if uploads:
        sections.append(uploads)
    return "\n\n".join(section for section in sections if section).strip()


def build_interview_reference(
    interview_id: str,
    owner_pk: int,
    question_indexes: tuple[int, ...] | list[int] = (),
) -> str:
    """Compatibility wrapper used by automatic debrief context injection."""
    reference = load_interview_reference(interview_id, owner_pk)
    return render_interview_reference(reference, question_indexes) if reference else ""


def _question_from_row(row: InterviewQA) -> InterviewQuestionReference:
    return InterviewQuestionReference(
        order_idx=row.order_idx,
        phase=row.phase or "",
        question=row.question or "",
        answer=row.answer or "",
        score=row.score,
        critique=row.critique or "",
        improved_answer=row.improved_answer or "",
        tags=tuple(_parse_tags(row.key_points_json)),
    )


def _render_question_details(
    questions: tuple[InterviewQuestionReference, ...],
    question_indexes: tuple[int, ...] | list[int],
) -> str:
    by_index = {question.index: question for question in questions}
    selected = [
        by_index[index]
        for index in dict.fromkeys(question_indexes)
        if index in by_index
    ]
    if not selected:
        return ""

    sections = ["## 本轮重点题目（完整内容）"]
    for question in selected:
        lines = [
            f"### Q{question.index}"
            + (f" · {question.phase}" if question.phase else ""),
            f"- 问题: {question.question or '（空）'}",
            f"- 候选人回答: {question.answer or '（未作答）'}",
            f"- 评分: {_score_text(question.score)}",
        ]
        if question.critique:
            lines.append(f"- 点评: {question.critique}")
        if question.improved_answer:
            lines.append(f"- 优化回答: {question.improved_answer}")
        if question.tags:
            lines.append(f"- 知识点: {'、'.join(question.tags)}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _render_uploads(reference: InterviewReference) -> str:
    lines: list[str] = []
    if reference.audio_file_asset_id:
        lines.append(
            f"- 音视频文件已上传 (file_asset_id={reference.audio_file_asset_id})"
        )
    if reference.resume_id:
        lines.append(f"- 使用个人简历 (resume_id={reference.resume_id})")
    if reference.resume_file_asset_id:
        lines.append(f"- 简历已上传 (file_asset_id={reference.resume_file_asset_id})")
    if reference.jd_file_asset_id:
        lines.append(f"- 岗位 JD 已上传 (file_asset_id={reference.jd_file_asset_id})")
    return "## 关联文件\n" + "\n".join(lines) if lines else ""


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _score_text(value: float | None) -> str:
    return "未评分" if value is None else f"{value:g}/10"


__all__ = [
    "InterviewQuestionReference",
    "InterviewReference",
    "build_interview_reference",
    "load_interview_reference",
    "render_interview_reference",
]
