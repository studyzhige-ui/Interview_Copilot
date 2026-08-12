"""Build the bounded, shared context used after an interview is analyzed."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def build_analysis_context(
    analysis_json: str | dict[str, Any] | None,
    qa_rows: Iterable[Any],
) -> str:
    """Render report evidence without embedding transcripts or full answers."""
    sections = [
        build_report_context(analysis_json),
        build_question_index(qa_rows),
    ]
    return "\n\n".join(section for section in sections if section).strip()


def build_report_context(analysis_json: str | dict[str, Any] | None) -> str:
    """Render deterministic report evidence without any question bodies."""
    analysis = _parse_analysis(analysis_json)
    lines: list[str] = []

    overall = analysis.get("overall")
    if isinstance(overall, dict):
        section = ["## 综合表现", f"- 综合评分: {_score_text(overall.get('score'))}"]
        summary = str(overall.get("summary") or "").strip()
        if summary:
            section.append(summary)
        _append_list(section, "亮点", overall.get("strengths"))
        _append_list(section, "待提升", overall.get("weaknesses"))

        growth = overall.get("key_growth_areas")
        if isinstance(growth, list):
            actions: list[str] = []
            for item in growth:
                if not isinstance(item, dict):
                    continue
                area = str(item.get("area") or "").strip()
                next_step = str(item.get("next_step") or "").strip()
                text = "：".join(part for part in (area, next_step) if part)
                if text:
                    actions.append(text)
            _append_list(section, "下一步行动", actions)
        lines.append("\n".join(section))

    phases = analysis.get("phase_summary")
    if isinstance(phases, list) and phases:
        section = ["## 阶段表现"]
        for item in phases:
            if not isinstance(item, dict):
                continue
            name = str(item.get("phase_name") or item.get("phase") or "综合").strip()
            summary = str(item.get("summary") or "").strip()
            row = f"- {name} · {_score_text(item.get('score'))}"
            if summary:
                row += f"：{summary}"
            section.append(row)
        if len(section) > 1:
            lines.append("\n".join(section))

    radar = analysis.get("skill_radar")
    if isinstance(radar, dict) and radar:
        section = ["## 能力维度"]
        section.extend(
            f"- {dimension}: {_radar_score_text(score)}"
            for dimension, score in radar.items()
        )
        lines.append("\n".join(section))

    return "\n\n".join(lines).strip()


def build_question_index(qa_rows: Iterable[Any]) -> str:
    """Render the compact 1-based question catalog shared by chat and Agent."""
    questions = list(qa_rows)
    if questions:
        section = [f"## 题目索引（共 {len(questions)} 题）"]
        for position, qa in enumerate(questions, start=1):
            order_idx = _field(qa, "order_idx")
            index = order_idx + 1 if isinstance(order_idx, int) else position
            question = str(_field(qa, "question") or "").strip()
            section.append(
                f"- Q{index} · {_score_text(_field(qa, 'score'))}: {_truncate(question, 180)}"
            )
        return "\n".join(section)
    return ""


def _parse_analysis(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _append_list(section: list[str], label: str, value: Any) -> None:
    if not isinstance(value, list):
        return
    items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        return
    section.append(f"- {label}:")
    section.extend(f"  - {item}" for item in items[:5])


def _score_text(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "未评分"
    return f"{float(value):g}/10"


def _radar_score_text(value: Any) -> str:
    text = _score_text(value)
    return "未考察" if text == "未评分" else text


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


__all__ = ["build_analysis_context", "build_question_index", "build_report_context"]
