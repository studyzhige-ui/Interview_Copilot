"""One bounded preparation read for UI and Copilot, without provider calls.

Exact source spans are the authority. Lexical overlap only locates passages to
review: it is not semantic entailment, a fit score, or proof of a skill gap.
Extractive tailoring cannot add candidate claims or overwrite the saved resume.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from sqlalchemy.orm import Session
from app.career.application.resumes import resume_artifact_service as resumes
from app.interviews.application.mock_sources import resolve_job_description
from app.schemas.mock_preparation import MockPreparationRequest
from app.schemas.preparation import Excerpt, PreparationBrief, PreparationItem

DISCLAIMER = (
    "原文共词仅用于定位待核实证据，不是能力认证或匹配评分。未定位到证据不代表不会；"
    "练习目标是待验证问题，不是已确认的个人缺陷。简历摘录未经改写，不会写入职业档案。"
)
_STOP = frozenset(
    "the and for with from this that you your our have will are 工作 岗位 职责 要求 负责 经验 能力 公司 团队 相关 具有 熟悉".split()
)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_preparation_sources(command, *, resume_version_id, resume_text, jd_text):
    checks = (
        (command.resume_version_id, resume_version_id),
        (command.resume_sha256, content_hash(resume_text)),
        (command.jd_sha256, content_hash(jd_text)),
    )
    if any(expected is not None and expected != actual for expected, actual in checks):
        raise PreparationSourceChanged(
            "准备资料已更新，请重新核对简历和岗位说明后再启动练习。"
        )


class PreparationSourceChanged(ValueError):
    pass


def _excerpts(text: str, prefix: str, *, maximum: int) -> list[Excerpt]:
    result = []
    for line in re.finditer(r"[^\n]+", text):
        start, end = line.span()
        while start < end:
            stop = min(end, start + 700)
            raw = text[start:stop]
            left = len(raw) - len(raw.lstrip())
            right = len(raw.rstrip())
            if left < right:
                result.append(
                    Excerpt(
                        id=f"{prefix}{len(result) + 1:03d}",
                        start=start + left,
                        end=start + right,
                        text=raw[left:right],
                    )
                )
            if len(result) > maximum:
                raise ValueError("preparation_source_excerpt_capacity")
            start = stop
    return result


def _terms(text: str) -> set[str]:
    value = unicodedata.normalize("NFKC", text).casefold()
    terms = set(re.findall(r"[a-z][a-z0-9+#.-]{1,39}", value))
    for run in re.findall(r"[\u4e00-\u9fff]+", value):
        terms.update(run[i : i + 2] for i in range(len(run) - 1))
    return terms - _STOP


def build_preparation(
    db: Session, *, user_pk: int, command: MockPreparationRequest
) -> PreparationBrief:
    if not command.resume_id:
        raise ValueError("preparation_requires_saved_resume")
    resume = resumes.resolve_owned_resume(
        db, user_pk=user_pk, resume_id=command.resume_id
    )
    from app.interviews.application.interview_record_service import (
        interview_record_service,
    )

    interview_record_service.require_owned_job_opportunity(
        db, user_pk=user_pk, job_opportunity_id=command.job_opportunity_id
    )
    resume_text = resumes.read_resume_text(resume)
    if len(resume_text) > 60_000:
        raise ValueError("preparation_resume_capacity")
    jd_text = resolve_job_description(
        db,
        user_pk=user_pk,
        jd_text=command.jd_text,
        job_opportunity_id=command.job_opportunity_id,
        jd_snapshot_id=command.jd_snapshot_id,
        jd_snapshot_version=command.jd_snapshot_version,
    )
    check_preparation_sources(
        command,
        resume_version_id=resume.current_version.id,
        resume_text=resume_text,
        jd_text=jd_text,
    )
    chunks = _excerpts(resume_text, "r", maximum=256)
    requirements = _excerpts(jd_text, "j", maximum=128)
    terms = [(part, _terms(part.text)) for part in chunks]
    items = []
    selected = set()
    for requirement in requirements:
        wanted = _terms(requirement.text)
        candidates = sorted(
            ((part, tokens & wanted) for part, tokens in terms),
            key=lambda pair: (-len(pair[1]), pair[0].start),
        )
        leads = [(part, overlap) for part, overlap in candidates if overlap][:3]
        selected.update(part.id for part, _ in leads)
        items.append(
            PreparationItem(
                requirement=requirement,
                evidence_candidates=[part for part, _ in leads],
                shared_terms=sorted(set().union(*(overlap for _, overlap in leads))),
                status="review_evidence" if leads else "evidence_not_located",
                practice_focus=f"围绕岗位原文“{requirement.text}”进行专项练习。通过问题核实理解、方案与取舍；只陈述真实经历，没有实践经历时明确说明。",
            )
        )
    extracts = [part for part in chunks if part.id in selected]
    resume_hash, jd_hash = content_hash(resume_text), content_hash(jd_text)
    pinned = command.model_copy(
        update={
            "resume_id": resume.artifact.id,
            "resume_version_id": resume.current_version.id,
            "resume_sha256": resume_hash,
            "jd_sha256": jd_hash,
        }
    )
    identity = json.dumps(
        [
            "source-excerpts-v1",
            resume.artifact.id,
            resume.current_version.id,
            resume_hash,
            jd_hash,
            command.job_opportunity_id,
            command.jd_snapshot_id,
            command.jd_snapshot_version,
        ],
        ensure_ascii=False,
    )
    snapshot = content_hash(identity)
    lines = [
        "# 面试准备笔记",
        "",
        DISCLAIMER,
        "",
        f"资料快照：{snapshot}",
        f"简历版本：{resume.current_version.id}",
        f"简历 SHA256：{resume_hash}",
        f"JD SHA256：{jd_hash}",
        "",
        "## 岗位原文与待核实证据",
    ]
    for item in items:
        lines += [
            "",
            f"### {item.requirement.id}",
            json.dumps(item.requirement.text, ensure_ascii=False),
        ]
        for part in item.evidence_candidates:
            lines.append(
                f"简历原文 {part.id} [{part.start}:{part.end}]："
                + json.dumps(part.text, ensure_ascii=False)
            )
        if not item.evidence_candidates:
            lines.append("未定位到共词证据，需用户核实；不是能力缺失结论。")
        lines += ["待练习：" + item.practice_focus]
    lines += ["", "## 岗位相关简历原文摘录（不是完整简历）", ""]
    lines += [json.dumps(part.text, ensure_ascii=False) for part in extracts]
    lines += ["", f"未选入 {len(chunks) - len(extracts)} 段原文；原始简历未修改。"]
    return PreparationBrief(
        snapshot_id=snapshot,
        resume_version_id=resume.current_version.id,
        resume_sha256=resume_hash,
        jd_sha256=jd_hash,
        items=items,
        resume_excerpts=extracts,
        omitted_resume_excerpt_count=len(chunks) - len(extracts),
        start_request=pinned,
        markdown="\n".join(lines) + "\n",
        disclaimer=DISCLAIMER,
    )
