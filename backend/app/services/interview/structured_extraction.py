"""Structured extraction of resume + JD into ref-id keyed evidence pools.

This is what makes the mock interview feel *targeted*: every interview question
generated downstream must declare which evidence it probes (`grounding_refs`).
Without ref ids the LLM happily slides into generic eight-part-essay questions.

Output shapes
-------------
ResumeEvidence:
    {
      "experiences": [
        { "ref_id": "exp_1", "company": "...", "role": "...", "period": "...",
          "highlights": [
            { "ref_id": "exp_1.h1", "text": "...", "topics": ["..."] }
          ]
        }
      ],
      "projects":      [ { "ref_id": "proj_1", "name": "...", "highlights": [...] } ],
      "skills_claimed": ["Go", "Python", "..."]
    }

JDRequirements:
    {
      "must_have":    [ { "ref_id": "req_1", "skill": "...", "depth": "expert" } ],
      "nice_to_have": [ { "ref_id": "nice_1", "skill": "..." } ],
      "responsibilities": [ { "ref_id": "resp_1", "text": "..." } ],
      "seniority": "junior" | "mid" | "senior" | "staff+",
      "domain":    "...",
    }

Both extractors are single-call (one LLM each). Failures degrade to empty
structures so the rest of the pipeline keeps working — grounding is best-effort.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.rag.embeddings import agent_fast_llm

logger = logging.getLogger(__name__)


RESUME_EXTRACT_PROMPT = """请把下面的简历正文结构化抽取为面试系统使用的"证据池"。

要求：
1. 每个原子项给出稳定的 ref_id（实验性，但同一次抽取内必须唯一）。
2. experiences：工作经历列表，每条带 highlights（量化数字、技术决策、规模、影响）。
3. projects：项目列表（独立或工作项目均可）。
4. skills_claimed：候选人明确声明掌握的技术 / 工具 / 框架。
5. 输出严格 JSON，不要任何额外文字。

ref_id 规范：
- experiences[i].ref_id = "exp_{i+1}"
- experiences[i].highlights[j].ref_id = "exp_{i+1}.h{j+1}"
- projects[i].ref_id = "proj_{i+1}"
- projects[i].highlights[j].ref_id = "proj_{i+1}.h{j+1}"

输出 JSON：
{{
  "experiences": [
    {{
      "ref_id": "exp_1",
      "company": "公司名",
      "role": "岗位",
      "period": "时间段",
      "highlights": [
        {{ "ref_id": "exp_1.h1", "text": "原文亮点", "topics": ["性能", "推荐"] }}
      ]
    }}
  ],
  "projects": [
    {{
      "ref_id": "proj_1",
      "name": "项目名",
      "summary": "1 句话项目描述",
      "highlights": [
        {{ "ref_id": "proj_1.h1", "text": "原文亮点", "topics": ["..."] }}
      ]
    }}
  ],
  "skills_claimed": ["Go", "Python", "Redis"]
}}

简历正文：
{resume_text}"""


JD_EXTRACT_PROMPT = """请把下面的岗位 JD 结构化抽取为面试系统使用的"要求池"，并推断 seniority。

要求：
1. must_have：JD 中明确必须的硬技能 / 经验，每条带 depth（expert / proficient / basic）。
2. nice_to_have：加分项。
3. responsibilities：核心职责描述，每条带 ref_id。
4. seniority：从 JD 的语气、年限要求、责任范围推断，取值 junior / mid / senior / staff+。
5. domain：行业 / 业务域（fintech / e-commerce / infra / ml / ...）。
6. 输出严格 JSON。

ref_id 规范：req_{{i+1}} / nice_{{i+1}} / resp_{{i+1}}。

输出 JSON：
{{
  "must_have":    [ {{ "ref_id": "req_1",  "skill": "Python 后端",     "depth": "expert" }} ],
  "nice_to_have": [ {{ "ref_id": "nice_1", "skill": "Rust" }} ],
  "responsibilities": [ {{ "ref_id": "resp_1", "text": "..." }} ],
  "seniority": "senior",
  "domain":    "fintech"
}}

JD 正文：
{jd_text}"""


def _empty_resume() -> dict[str, Any]:
    return {"experiences": [], "projects": [], "skills_claimed": []}


def _empty_jd() -> dict[str, Any]:
    return {
        "must_have": [],
        "nice_to_have": [],
        "responsibilities": [],
        "seniority": "mid",
        "domain": "",
    }


async def extract_resume_evidence(resume_text: str) -> dict[str, Any]:
    text = (resume_text or "").strip()
    if not text:
        return _empty_resume()

    prompt = RESUME_EXTRACT_PROMPT.format(resume_text=text[:8000])
    try:
        response = await agent_fast_llm.acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(str(response.text).strip())
        if not isinstance(parsed, dict):
            return _empty_resume()
        return _normalize_resume(parsed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Resume evidence extraction failed: %s", exc)
        return _empty_resume()


async def extract_jd_requirements(jd_text: str) -> dict[str, Any]:
    text = (jd_text or "").strip()
    if not text:
        return _empty_jd()

    prompt = JD_EXTRACT_PROMPT.format(jd_text=text[:6000])
    try:
        response = await agent_fast_llm.acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(str(response.text).strip())
        if not isinstance(parsed, dict):
            return _empty_jd()
        return _normalize_jd(parsed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("JD requirements extraction failed: %s", exc)
        return _empty_jd()


def _normalize_resume(raw: dict[str, Any]) -> dict[str, Any]:
    out = _empty_resume()
    experiences = raw.get("experiences") if isinstance(raw.get("experiences"), list) else []
    for i, exp in enumerate(experiences):
        if not isinstance(exp, dict):
            continue
        ref_id = str(exp.get("ref_id") or f"exp_{i + 1}")
        highlights_in = exp.get("highlights") if isinstance(exp.get("highlights"), list) else []
        highlights_out: list[dict[str, Any]] = []
        for j, h in enumerate(highlights_in):
            if isinstance(h, dict):
                text = str(h.get("text") or "").strip()
                if not text:
                    continue
                highlights_out.append({
                    "ref_id": str(h.get("ref_id") or f"{ref_id}.h{j + 1}"),
                    "text": text,
                    "topics": [str(t) for t in (h.get("topics") or []) if isinstance(t, (str, int))],
                })
            elif isinstance(h, str) and h.strip():
                highlights_out.append({
                    "ref_id": f"{ref_id}.h{j + 1}",
                    "text": h.strip(),
                    "topics": [],
                })
        out["experiences"].append({
            "ref_id": ref_id,
            "company": str(exp.get("company") or ""),
            "role": str(exp.get("role") or ""),
            "period": str(exp.get("period") or ""),
            "highlights": highlights_out,
        })

    projects = raw.get("projects") if isinstance(raw.get("projects"), list) else []
    for i, proj in enumerate(projects):
        if not isinstance(proj, dict):
            continue
        ref_id = str(proj.get("ref_id") or f"proj_{i + 1}")
        highlights_in = proj.get("highlights") if isinstance(proj.get("highlights"), list) else []
        highlights_out = []
        for j, h in enumerate(highlights_in):
            if isinstance(h, dict):
                text = str(h.get("text") or "").strip()
                if not text:
                    continue
                highlights_out.append({
                    "ref_id": str(h.get("ref_id") or f"{ref_id}.h{j + 1}"),
                    "text": text,
                    "topics": [str(t) for t in (h.get("topics") or []) if isinstance(t, (str, int))],
                })
            elif isinstance(h, str) and h.strip():
                highlights_out.append({
                    "ref_id": f"{ref_id}.h{j + 1}",
                    "text": h.strip(),
                    "topics": [],
                })
        out["projects"].append({
            "ref_id": ref_id,
            "name": str(proj.get("name") or ""),
            "summary": str(proj.get("summary") or ""),
            "highlights": highlights_out,
        })

    skills = raw.get("skills_claimed") if isinstance(raw.get("skills_claimed"), list) else []
    out["skills_claimed"] = [str(s).strip() for s in skills if isinstance(s, (str, int)) and str(s).strip()]
    return out


def _normalize_jd(raw: dict[str, Any]) -> dict[str, Any]:
    out = _empty_jd()
    for key, prefix in (("must_have", "req"), ("nice_to_have", "nice"), ("responsibilities", "resp")):
        items = raw.get(key) if isinstance(raw.get(key), list) else []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            ref_id = str(item.get("ref_id") or f"{prefix}_{i + 1}")
            text = str(item.get("skill") or item.get("text") or "").strip()
            if not text:
                continue
            entry: dict[str, Any] = {"ref_id": ref_id}
            if key == "responsibilities":
                entry["text"] = text
            else:
                entry["skill"] = text
                depth = str(item.get("depth") or "").strip()
                if depth:
                    entry["depth"] = depth
            out[key].append(entry)

    seniority = str(raw.get("seniority") or "").strip().lower()
    if seniority in {"junior", "mid", "senior", "staff+", "staff", "principal"}:
        out["seniority"] = "staff+" if seniority in {"staff", "principal"} else seniority
    out["domain"] = str(raw.get("domain") or "").strip()
    return out


# ── Helpers used by plan/conduct prompts ────────────────────────────────


def fundamentals_quota_for(seniority: str) -> float:
    """Fraction of technical-phase questions allowed to be generic 八股."""
    return {
        "junior": 0.30,
        "mid": 0.20,
        "senior": 0.10,
        "staff+": 0.05,
    }.get((seniority or "mid").lower(), 0.20)


def format_resume_pool(evidence: dict[str, Any], *, char_cap: int = 2500) -> str:
    """Compact markdown rendering of ResumeEvidence for prompt injection."""
    lines: list[str] = []
    for exp in evidence.get("experiences") or []:
        head = f"[{exp.get('ref_id')}] {exp.get('company','')} · {exp.get('role','')} · {exp.get('period','')}".strip()
        lines.append(head)
        for h in exp.get("highlights") or []:
            lines.append(f"  - [{h.get('ref_id')}] {h.get('text','')}")
    for proj in evidence.get("projects") or []:
        head = f"[{proj.get('ref_id')}] 项目: {proj.get('name','')}"
        lines.append(head)
        if proj.get("summary"):
            lines.append(f"  · {proj['summary']}")
        for h in proj.get("highlights") or []:
            lines.append(f"  - [{h.get('ref_id')}] {h.get('text','')}")
    skills = evidence.get("skills_claimed") or []
    if skills:
        lines.append(f"声明掌握技能：{', '.join(skills[:30])}")
    text = "\n".join(lines)
    return text[:char_cap]


def format_jd_pool(requirements: dict[str, Any], *, char_cap: int = 1500) -> str:
    lines: list[str] = []
    if requirements.get("seniority"):
        lines.append(f"岗位级别：{requirements['seniority']}")
    if requirements.get("domain"):
        lines.append(f"业务域：{requirements['domain']}")
    must = requirements.get("must_have") or []
    if must:
        lines.append("必备能力 (must_have)：")
        for r in must:
            depth = f"（{r.get('depth')}）" if r.get("depth") else ""
            lines.append(f"  - [{r.get('ref_id')}] {r.get('skill','')}{depth}")
    nice = requirements.get("nice_to_have") or []
    if nice:
        lines.append("加分项 (nice_to_have)：")
        for r in nice:
            lines.append(f"  - [{r.get('ref_id')}] {r.get('skill','')}")
    resp = requirements.get("responsibilities") or []
    if resp:
        lines.append("核心职责：")
        for r in resp:
            lines.append(f"  - [{r.get('ref_id')}] {r.get('text','')}")
    return "\n".join(lines)[:char_cap]
