"""Build a "reference manifest" for a chat session bound to an interview.

Design rationale
================
A debrief chat needs the LLM to *see* what the interview was actually about —
without manually copying transcripts or analysis into every prompt the user
writes. Two engineering options were considered:

  A) **Snapshot on chat creation.** When the debrief chat is created, denormalize
     the interview's analysis + transcript into ``ChatSession.session_state``.
     Pros: zero per-turn cost. Cons: stale if the user edits a Q&A afterwards.

  B) **Lazy fetch per turn.** The context-assembly pipeline reads the chat's
     ``session_state['interview_id']`` on each query, joins on InterviewRecord,
     builds a compact manifest, fills the existing ``reference_material`` slot.
     Pros: always fresh; honors QA edits via ``PATCH /interview-records/{id}/qa/{idx}``;
     no schema migration. Cons: ~1 SQL roundtrip per turn (≈1ms).

We picked (B). It plugs into the existing 6-slot context window without any
new infrastructure, and the cost is dominated by the LLM call itself.

The output is a structured markdown block (~1–2k tokens) that goes straight
into the ``[Reference Material]`` section of the prompt — see
``app/services/chat/context_assembly_pipeline.py:PromptRenderer.render_answer_prompt``.
"""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord

logger = logging.getLogger(__name__)


# Soft cap on transcript / per-question excerpt sizes. Final assembly will
# still pass through the TokenBudget gate so this is just an early trim.
#
# Why 2400? With Chinese text averaging ~1.8 tokens/char, 2400 chars ≈ 4300
# tokens. The REFERENCE_MATERIAL_BUDGET is 2000 tokens but the pipeline doesn't
# yet hard-trim this slot (an upstream improvement) — so we self-cap here.
# Transcripts under this length are emitted in full.
_TRANSCRIPT_HARD_CAP_CHARS = 2400
_PER_QUESTION_TAKE = 5  # top-N weakest questions (or first-N if no scores)


def build_interview_reference(interview_id: str, user_id: str) -> str:
    """Return a compact markdown reference for the given interview record.

    Empty string if the record doesn't exist, doesn't belong to the user, or
    has no usable data. Empty is fine — caller (the pipeline) just skips the
    reference_material slot.
    """
    db: Session = SessionLocal()
    try:
        record = (
            db.query(InterviewRecord)
            .filter(InterviewRecord.id == interview_id, InterviewRecord.user_id == user_id)
            .first()
        )
        if record is None:
            return ""
        qa_rows = (
            db.query(InterviewQA)
            .filter(InterviewQA.record_id == interview_id)
            .order_by(InterviewQA.order_idx)
            .all()
        )
        return _render(record, qa_rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("build_interview_reference failed for %s: %s", interview_id, exc)
        return ""
    finally:
        db.close()


def _render(record: InterviewRecord, qa_rows: list[InterviewQA]) -> str:
    lines: list[str] = []
    header_bits = [f"# 当前复盘的面试: {record.title or '未命名'}"]
    meta_bits = [f"record_id: {record.id}"]
    if record.tag:
        meta_bits.append(f"标签: {record.tag}")
    if record.source:
        meta_bits.append(f"来源: {record.source}")
    if record.status:
        meta_bits.append(f"状态: {record.status}")
    header_bits.append(" · ".join(meta_bits))
    header_bits.append(
        "（以下材料由系统在每轮对话开始时自动注入；如需完整原文，"
        f"前端/工具调用 GET /api/v1/interview-records/{record.id}）"
    )
    lines.append("\n".join(header_bits))

    analysis = _parse_analysis(record.analysis_json)
    overall = analysis.get("overall") if isinstance(analysis, dict) else None

    if isinstance(overall, dict):
        score = overall.get("score")
        summary = (overall.get("summary") or overall.get("feedback") or "").strip()
        strengths = overall.get("strengths") or []
        weaknesses = overall.get("weaknesses") or []
        plan = overall.get("improvement_plan") or []

        ovr_bits = ["## 综合表现"]
        if isinstance(score, (int, float)):
            ovr_bits.append(f"- 评分: {score}")
        if summary:
            ovr_bits.append(f"- 评语: {summary}")
        if strengths:
            ovr_bits.append("- 亮点:")
            for s in strengths[:5]:
                ovr_bits.append(f"  - {str(s).strip()}")
        if weaknesses:
            ovr_bits.append("- 待提升:")
            for w in weaknesses[:5]:
                ovr_bits.append(f"  - {str(w).strip()}")
        if plan:
            ovr_bits.append("- 改进计划:")
            for p in plan[:5]:
                step = (
                    str(p.get("area") or p.get("text") or "").strip()
                    if isinstance(p, dict)
                    else str(p).strip()
                )
                if step:
                    ovr_bits.append(f"  - {step}")
        lines.append("\n".join(ovr_bits))

    if qa_rows:
        ranked = sorted(qa_rows, key=lambda r: (r.score if r.score is not None else 999, r.order_idx))
        ranked = ranked[:_PER_QUESTION_TAKE]
        qa_bits = [f"## 逐题摘要（共 {len(qa_rows)} 题，按分数升序取前 {len(ranked)} 题）"]
        for qa in ranked:
            q = (qa.question or "").strip()
            a = (qa.answer or "").strip()
            critique = (qa.critique or "").strip()
            improved = (qa.improved_answer or "").strip()
            header = f"### Q{qa.order_idx + 1}"
            if qa.score is not None:
                header += f" · 评分 {qa.score}"
            qa_bits.append(header)
            if q:
                qa_bits.append(f"- 问题: {_truncate(q, 200)}")
            if a:
                qa_bits.append(f"- 我的回答: {_truncate(a, 300)}")
            if critique:
                qa_bits.append(f"- 点评: {_truncate(critique, 200)}")
            if improved:
                qa_bits.append(f"- 优化版回答: {_truncate(improved, 300)}")
        lines.append("\n".join(qa_bits))

    if record.transcript:
        full = record.transcript.strip()
        full_len = len(full)
        if full_len <= _TRANSCRIPT_HARD_CAP_CHARS:
            # Fits in the budget — emit in full so the model has authoritative text.
            lines.append(f"## 原始转录（全文 {full_len} 字符）\n{full}")
        else:
            head = full[: _TRANSCRIPT_HARD_CAP_CHARS]
            tail_hint = (
                f"\n\n…（已截取前 {_TRANSCRIPT_HARD_CAP_CHARS} 字符，全文 {full_len} 字符。"
                f"完整内容可通过 GET /api/v1/interview-records/{record.id} 的 `transcript` 字段获取；"
                "未来可向用户暴露 get_full_transcript 工具来按段拉取。）"
            )
            lines.append(
                f"## 原始转录（节选 · 前 {_TRANSCRIPT_HARD_CAP_CHARS}/{full_len} 字符）\n{head}{tail_hint}"
            )

    # Upload pointers — tell the model what was provided. Actual file bodies
    # are reachable via /upload/audio/direct or /knowledge/documents if a tool
    # needs them; this is just disclosure.
    upload_bits = []
    if record.audio_upload_id:
        upload_bits.append(f"- 音视频文件已上传 (upload_id={record.audio_upload_id})")
    if record.resume_upload_id:
        upload_bits.append(f"- 简历已上传 (upload_id={record.resume_upload_id})")
    if record.jd_upload_id:
        upload_bits.append(f"- 岗位 JD 已上传 (document_id={record.jd_upload_id})")
    if upload_bits:
        lines.append("## 关联文件\n" + "\n".join(upload_bits))

    return "\n\n".join(lines).strip()


def _parse_analysis(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _truncate(s: str, n: int) -> str:
    s = s.strip().replace("\r\n", "\n")
    if len(s) <= n:
        return s
    return s[: n].rstrip() + "…"


__all__ = ["build_interview_reference"]
