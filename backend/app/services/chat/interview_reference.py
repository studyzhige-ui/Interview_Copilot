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
# Per-question emission: only ``question`` and ``score`` (no improved_answer
# / no full critique). Rationale (per product spec): improved_answer is
# nearly as bulky as the transcript itself — and the model can always pull
# it on demand via RAG / the record-detail endpoint when discussion
# actually drifts into a specific Q. Front-loading every full answer just
# burns prompt cache space.
_PER_QUESTION_TAKE = 12


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
        # Light-touch QA index: just question + score. Full answers /
        # critiques / improved-answers stay in the database and get pulled
        # on demand by the agent's RAG layer when a specific Q is discussed.
        ranked = sorted(qa_rows, key=lambda r: r.order_idx)[:_PER_QUESTION_TAKE]
        qa_bits = [f"## 题目清单（共 {len(qa_rows)} 题，列出前 {len(ranked)} 题；详情按需通过 RAG 拉取）"]
        for qa in ranked:
            q = (qa.question or "").strip()
            score_str = f" · 评分 {qa.score}" if qa.score is not None else ""
            header = f"- Q{qa.order_idx + 1}{score_str}"
            if q:
                header += f": {_truncate(q, 180)}"
            qa_bits.append(header)
        lines.append("\n".join(qa_bits))

    # Debrief 摘要——分析 pipeline 末尾由 LLM 生成的 200-400 字浓缩版。
    # 用它替代原始转录全文（转录太大，会把 prompt cache 撑爆；具体内容
    # 想看时通过 GET /interview-records/{id} 的 transcript 字段拉，或者
    # 让 agent 走 RAG）。debrief_summary 为 NULL 时（mock 模式 / 旧记录）
    # 退化到截断转录，保证最低限度的对话上下文。
    if (record.debrief_summary or "").strip():
        lines.append(f"## 本次面试浓缩摘要\n{record.debrief_summary.strip()}")
    elif record.transcript:
        full = record.transcript.strip()
        if len(full) <= _TRANSCRIPT_HARD_CAP_CHARS:
            lines.append(f"## 原始转录（debrief_summary 缺失，回退到全文，{len(full)} 字符）\n{full}")
        else:
            head = full[:_TRANSCRIPT_HARD_CAP_CHARS]
            lines.append(
                f"## 原始转录（debrief_summary 缺失，节选前 {_TRANSCRIPT_HARD_CAP_CHARS}/{len(full)} 字符）\n{head}"
            )

    # 简历全文——围绕简历问问题是绝大多数面试的主线，所以这块对回答质量
    # 收益最高。``resume_text_snapshot`` 由上传 pipeline 时一次性生成
    # 并 freeze 在 record 行上（即便后续用户删原始文件也不丢）。空字符串
    # 表示该 record 当时没传简历——跳过即可。
    resume_snapshot = (record.resume_text_snapshot or "").strip()
    if resume_snapshot:
        lines.append(f"## 候选人简历全文\n{resume_snapshot}")

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
