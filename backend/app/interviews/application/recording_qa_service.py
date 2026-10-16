"""Extract readable QA from fallible ASR, preserving references for playback."""

from __future__ import annotations

import json
from typing import Any, Literal

from llama_index.core.llms import LLM
from pydantic import BaseModel, ConfigDict, Field

from app.core.llm_client_factory import get_internal_llm
from app.core.structured_json import strict_json
from app.media.application.transcript_evidence import TranscriptEvidence
from app.prompts.recording_qa import QA_EXTRACTION_PROMPT


class QAExtractionError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SpeakerRole(_Contract):
    speaker_id: str
    role: Literal["interviewer", "candidate", "unknown"]


class SourceRange(_Contract):
    start_word_id: str
    end_word_id: str


class ExtractedQA(_Contract):
    question: str = Field(min_length=1)
    answer: str
    question_sources: list[SourceRange] = Field(min_length=1)
    answer_sources: list[SourceRange]
    phase: Literal[
        "opening",
        "resume",
        "project",
        "technical",
        "behavioral",
        "career",
        "reverse_qa",
        "closing",
        "general",
    ]
    parent_index: int | None = Field(default=None, ge=1)


class Extraction(_Contract):
    qa: list[ExtractedQA] = Field(min_length=1)
    speaker_roles: list[SpeakerRole]
    warnings: list[str] = Field(default_factory=list)


class TranscriptStructure(_Contract):
    schema_version: Literal[2] = 2
    revision: int = 1
    speaker_roles: list[SpeakerRole]


class ExtractionQuality(_Contract):
    # Completion means extraction succeeded, not a measured semantic accuracy.
    status: Literal["complete"] = "complete"
    warnings: list[str]


class ExtractedInterview(_Contract):
    structure: TranscriptStructure
    qa_pairs: list[dict[str, Any]]
    quality: ExtractionQuality


def _source_ids(evidence: TranscriptEvidence, ranges: list[SourceRange]) -> list[str]:
    index = evidence.word_index()
    positions: list[int] = []
    for span in ranges:
        start, end = index.get(span.start_word_id), index.get(span.end_word_id)
        if start is None or end is None or start > end:
            raise ValueError("QA cites an unknown or reversed source range")
        if positions and start <= positions[-1]:
            raise ValueError("QA source ranges must be ordered and nonoverlapping")
        positions.extend(range(start, end + 1))
    return [evidence.words[pos].word_id for pos in positions]


async def extract_recording_qa(
    evidence: TranscriptEvidence,
    *,
    llm: LLM | None = None,
    confirmed_roles: dict[str, str] | None = None,
) -> ExtractedInterview:
    speakers = {word.speaker_id for word in evidence.words if word.speaker_id}
    overrides = confirmed_roles or {}
    if set(overrides) - speakers or any(
        role not in {"candidate", "interviewer", "unknown"}
        for role in overrides.values()
    ):
        raise QAExtractionError("speaker_roles_invalid", "invalid user roles")

    # Every word is supplied once; do not truncate the conversation or infer QA
    # boundaries from acoustic speaker changes. IDs locate audio, not wording.
    source = "\n".join(
        f"{word.word_id}|{word.speaker_id or 'unknown'}|{word.text}"
        for word in evidence.words
    )
    response = await (llm or get_internal_llm("worker")).acomplete(
        QA_EXTRACTION_PROMPT.format(
            schema=json.dumps(Extraction.model_json_schema(), ensure_ascii=False),
            confirmed_roles=json.dumps(overrides, ensure_ascii=False),
            transcript=source,
        ),
        response_format={"type": "json_object"},
    )
    try:
        extracted = Extraction.model_validate(strict_json(response.text))
        roles = {role.speaker_id: role for role in extracted.speaker_roles}
        if len(roles) != len(extracted.speaker_roles) or set(roles) - speakers:
            raise ValueError("speaker roles must cite distinct source speakers")
        for speaker, role in overrides.items():
            roles[speaker] = SpeakerRole(speaker_id=speaker, role=role)
        pairs = []
        words = evidence.word_map()
        for number, qa in enumerate(extracted.qa, 1):
            if qa.parent_index is not None and qa.parent_index >= number:
                raise ValueError("follow-up must reference an earlier question")
            question_ids = _source_ids(evidence, qa.question_sources)
            answer_ids = _source_ids(evidence, qa.answer_sources)
            if bool(qa.answer) != bool(answer_ids):
                raise ValueError("an answer and its source must be provided together")
            if set(question_ids) & set(answer_ids):
                raise ValueError("question and answer cannot cite the same words")
            cited = [words[key] for key in question_ids + answer_ids]
            starts = [word.start for word in cited if word.start is not None]
            ends = [word.end for word in cited if word.end is not None]
            pairs.append(
                {
                    "index": number,
                    "question": qa.question,
                    "answer": qa.answer,
                    "phase": qa.phase,
                    "is_follow_up": qa.parent_index is not None,
                    "parent_index": qa.parent_index,
                    "source_segment_start": min(starts) if starts else None,
                    "source_segment_end": max(ends) if ends else None,
                    "source_provenance": {
                        "evidence_schema_version": evidence.schema_version,
                        "structure_schema_version": 2,
                        "structure_revision": 1,
                        "question_word_ids": question_ids,
                        "answer_word_ids": answer_ids,
                    },
                }
            )
    except ValueError as exc:
        raise QAExtractionError("qa_extraction_invalid", str(exc)) from exc
    return ExtractedInterview(
        structure=TranscriptStructure(speaker_roles=list(roles.values())),
        qa_pairs=pairs,
        quality=ExtractionQuality(warnings=extracted.warnings),
    )
