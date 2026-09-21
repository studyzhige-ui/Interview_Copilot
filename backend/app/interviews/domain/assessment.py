"""Evidence-backed dimensions; labels and phases cannot manufacture ability.

A quote match proves provenance, not that the semantic judgment is true. Real
quality evaluation remains necessary. Numerical aggregation is deterministic.
"""

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.scoring import Score, mean_score

DIMENSIONS = ("系统设计", "编码能力", "基础知识", "沟通表达", "项目经验")
RUBRIC_VERSION = "interview-answer-10-v2"
WEIGHTS = {
    "technical": {
        "correctness": 4,
        "reasoning": 2,
        "evidence": 2,
        "tradeoffs": 1,
        "clarity": 1,
    },
    "resume_deep_dive": {
        "correctness": 4,
        "reasoning": 2,
        "evidence": 2,
        "tradeoffs": 1,
        "clarity": 1,
    },
    "behavioral": {
        "context": 2,
        "action": 3,
        "result": 3,
        "reflection": 1,
        "clarity": 1,
    },
    "self_intro": {"relevance": 4, "structure": 3, "credibility": 2, "clarity": 1},
    "reverse_qa": {"value": 6, "targeting": 2, "clarity": 2},
}


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(min_length=1, max_length=40)
    score: Score
    reason: str = Field(min_length=1, max_length=1000)


class CompetencyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dimension: Literal["系统设计", "编码能力", "基础知识", "沟通表达", "项目经验"]
    score: Score
    answer_quote: str = Field(min_length=1, max_length=3000)
    reason: str = Field(min_length=1, max_length=1500)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.answer_quote.strip() or not self.reason.strip():
            raise ValueError("evidence and reason must not be blank")
        return self


def weights_for(phase: str) -> dict[str, int]:
    return WEIGHTS.get(phase, WEIGHTS["technical"])


def criteria_score(raw: Any, source: dict[str, Any]) -> tuple[float, list[dict]]:
    if not isinstance(raw, list) or len(raw) > 8:
        raise ValueError("criteria must be a bounded list")
    criteria = [Criterion.model_validate(item) for item in raw]
    weights = weights_for(str(source.get("phase") or "general"))
    keys = [item.key for item in criteria]
    if len(keys) != len(set(keys)) or set(keys) != set(weights):
        raise ValueError("criteria must match the selected question rubric exactly")
    if any(not item.reason.strip() for item in criteria):
        raise ValueError("criterion reasoning is missing")
    score = round(
        sum(item.score * weights[item.key] for item in criteria)
        / sum(weights.values()),
        1,
    )
    return score, [item.model_dump() for item in criteria]


def verify_competencies(raw: Any, source: dict[str, Any]) -> list[dict]:
    if not isinstance(raw, list) or len(raw) > len(DIMENSIONS):
        raise ValueError("competency evidence must be a bounded list")
    answer = source.get("answer") or ""
    seen = set()
    result = []
    for value in raw:
        item = CompetencyEvidence.model_validate(value)
        if item.dimension in seen:
            raise ValueError("duplicate competency")
        seen.add(item.dimension)
        if item.answer_quote not in answer:
            raise ValueError("competency quote does not occur in this answer")
        if item.dimension == "编码能力" and not source.get("verified_code_artifact"):
            # Current voice/text interview does not produce a verified executable
            # coding artifact. Concept talk may support 基础知识, not execution.
            raise ValueError(
                "coding competence needs a verified coding artifact; do not infer it from keywords"
            )
        result.append(item.model_dump())
    return result


def aggregate_competencies(
    questions: list[dict],
) -> tuple[dict[str, float | None], dict[str, list[dict]]]:
    evidence: dict[str, list[dict]] = {dimension: [] for dimension in DIMENSIONS}
    for question in questions:
        if question.get("score") is None or question.get("analysis_failed"):
            continue
        raw = question.get("competency_evidence") or []
        items = verify_competencies(raw, question)
        for item in items:
            evidence[item["dimension"]].append(
                {
                    **item,
                    "question_index": question["index"],
                    "qa_id": question.get("qa_id"),
                    "source_version": question.get("source_version"),
                }
            )
    radar = {
        dimension: mean_score([item["score"] for item in items])
        for dimension, items in evidence.items()
    }
    return radar, evidence
