"""ID-only conversation structure and deterministic QA projection.

LLMs classify roles, dialogue acts and question relationships.  They never
author source text.  The service validates every identity against immutable
TranscriptEvidence and reconstructs display text in code.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from typing import Any, Literal

from llama_index.core.llms import LLM
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.llm_client_factory import get_internal_llm
from app.prompts.interview_transcript_structure import (
    QA_EPISODE_PROMPT,
    SPEAKER_ROLE_PROMPT,
    UTTERANCE_STRUCTURE_PROMPT,
)
from app.services.voice.transcript_evidence import (
    TranscriptEvidence,
    is_substantive_word,
    render_word_ids,
    strict_display_hidden_words,
)


STRUCTURE_SCHEMA_VERSION = 1
_WINDOW_WORDS = 420
_SEMANTIC_ROLE_MIN_CONFIDENCE = 0.65
_ALLOWED_PUNCTUATION = {
    "，",
    "。",
    "？",
    "！",
    "：",
    "；",
    ",",
    ".",
    "?",
    "!",
    ":",
    ";",
}


class TranscriptProjectionError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class SpeakerRole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_id: str
    role: Literal["interviewer", "candidate", "unknown"]
    confidence: float = Field(ge=0, le=1)


class _SpeakerRoleEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    speaker_roles: list[SpeakerRole]


class PunctuationEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_word_id: str
    mark: str


class _RawUtterance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_word_id: str
    end_word_id: str
    role: Literal["interviewer", "candidate"] | None = None
    dialogue_act: Literal[
        "question",
        "answer",
        "acknowledgement",
        "context",
        "interruption",
        "closing",
        "noise",
    ]
    confidence: float = Field(ge=0, le=1)
    punctuation: list[PunctuationEdit] = Field(default_factory=list)


class _UtteranceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utterances: list[_RawUtterance]


class UtteranceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utterance_id: str = Field(pattern=r"^u\d{4}$")
    speaker_id: str | None = None
    role: Literal["interviewer", "candidate", "unknown"]
    role_source: Literal[
        "speaker_map",
        "speaker_map_repaired",
        "semantic_recovery",
        "unresolved",
    ]
    start_word_id: str
    end_word_id: str
    dialogue_act: Literal[
        "question",
        "answer",
        "acknowledgement",
        "context",
        "interruption",
        "closing",
        "noise",
    ]
    confidence: float = Field(ge=0, le=1)
    punctuation: list[PunctuationEdit] = Field(default_factory=list)


class _RawEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_utterance_ids: list[str] = Field(min_length=1)
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
    is_follow_up: bool = False
    parent_episode_index: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def unique_questions(self) -> "_RawEpisode":
        if len(self.question_utterance_ids) != len(set(self.question_utterance_ids)):
            raise ValueError("question utterance ids must be unique")
        return self


class _EpisodeEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episodes: list[_RawEpisode]


class TranscriptStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = STRUCTURE_SCHEMA_VERSION
    revision: int = Field(default=1, ge=1)
    speaker_roles: list[SpeakerRole]
    utterances: list[UtteranceProjection]


class ProjectionQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aligned_word_ratio: float = Field(ge=0, le=1)
    known_speaker_word_ratio: float = Field(ge=0, le=1)
    role_resolved_substantive_word_ratio: float = Field(ge=0, le=1)
    candidate_substantive_word_coverage: float = Field(ge=0, le=1)
    question_word_coverage: float = Field(ge=0, le=1)
    hidden_word_ratio: float = Field(ge=0, le=1)
    overlap_word_ratio: float = Field(ge=0, le=1)
    low_confidence_episode_count: int = Field(ge=0)
    status: Literal["complete", "needs_review"]


class ProjectedInterview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    structure: TranscriptStructure
    qa_pairs: list[dict[str, Any]]
    quality: ProjectionQuality


def _json_object(text: str) -> dict[str, Any]:
    value = str(text).strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    parsed = json.loads(value.strip())
    if not isinstance(parsed, dict):
        raise ValueError("model response must be a JSON object")
    return parsed


def _word_range(index: dict[str, int], start_id: str, end_id: str) -> range:
    if start_id not in index or end_id not in index:
        raise TranscriptProjectionError(
            "structure_projection_invalid", "model referenced an unknown word id"
        )
    start = index[start_id]
    end = index[end_id]
    if end < start:
        raise TranscriptProjectionError(
            "structure_projection_invalid", "word range is reversed"
        )
    return range(start, end + 1)


def _render_turn_samples(evidence: TranscriptEvidence) -> str:
    index = evidence.word_index()
    by_speaker: dict[str, list[str]] = {}
    for turn in evidence.acoustic_turns:
        if turn.speaker_id is None:
            continue
        speaker = turn.speaker_id
        if len(by_speaker.setdefault(speaker, [])) >= 16:
            continue
        word_range = _word_range(index, turn.start_word_id, turn.end_word_id)
        text = "".join(evidence.words[pos].text for pos in word_range).strip()
        if text:
            by_speaker[speaker].append(f"{turn.turn_id}|{text[:500]}")
    return "\n".join(
        f"speaker={speaker}\n" + "\n".join(samples)
        for speaker, samples in by_speaker.items()
    )


async def _infer_roles(
    evidence: TranscriptEvidence,
    llm: LLM,
) -> list[SpeakerRole]:
    speakers = sorted({word.speaker_id for word in evidence.words if word.speaker_id})
    if len(speakers) != 2:
        raise TranscriptProjectionError(
            "speaker_roles_ambiguous",
            f"expected exactly two aligned speakers, got {len(speakers)}",
        )
    response = await llm.acomplete(
        SPEAKER_ROLE_PROMPT.format(
            required_speakers=json.dumps(speakers, ensure_ascii=False),
            turns=_render_turn_samples(evidence),
        ),
        response_format={"type": "json_object"},
    )
    try:
        envelope = _SpeakerRoleEnvelope.model_validate(_json_object(response.text))
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise TranscriptProjectionError("speaker_roles_ambiguous", str(exc)) from exc
    role_by_speaker = {item.speaker_id: item for item in envelope.speaker_roles}
    if set(role_by_speaker) != set(speakers):
        raise TranscriptProjectionError(
            "speaker_roles_ambiguous", "role response did not cover exact speakers"
        )
    roles = {item.role for item in role_by_speaker.values()}
    if roles != {"interviewer", "candidate"} or any(
        item.confidence < 0.65 for item in role_by_speaker.values()
    ):
        raise TranscriptProjectionError(
            "speaker_roles_ambiguous", "speaker role confidence is insufficient"
        )
    return [role_by_speaker[speaker] for speaker in speakers]


def _windows(evidence: TranscriptEvidence) -> list[tuple[int, int]]:
    """Deterministic, complete word windows; never split or drop by characters."""

    return [
        (start, min(start + _WINDOW_WORDS, len(evidence.words)))
        for start in range(0, len(evidence.words), _WINDOW_WORDS)
    ]


def _window_prompt(evidence: TranscriptEvidence, start: int, end: int) -> str:
    return "\n".join(
        f"{word.word_id}|speaker={word.speaker_id or 'UNKNOWN'}|{word.text}"
        for word in evidence.words[start:end]
    )


def _validate_punctuation(
    edits: Sequence[PunctuationEdit], allowed_ids: set[str]
) -> list[PunctuationEdit]:
    seen: set[str] = set()
    result: list[PunctuationEdit] = []
    for edit in edits:
        if (
            edit.after_word_id not in allowed_ids
            or edit.after_word_id in seen
            or edit.mark not in _ALLOWED_PUNCTUATION
        ):
            raise TranscriptProjectionError(
                "structure_projection_invalid", "invalid punctuation edit"
            )
        seen.add(edit.after_word_id)
        result.append(edit)
    return result


def _resolve_utterance_role(
    evidence: TranscriptEvidence,
    positions: range,
    role_map: dict[str, str],
    raw: _RawUtterance,
) -> tuple[Literal["interviewer", "candidate", "unknown"], str]:
    """Resolve an utterance role without rewriting its acoustic evidence.

    Diarization occasionally emits a one-word speaker flip inside an otherwise
    stable turn, especially when forced alignment gives that word an unusually
    long interval.  A dominant mapped role may absorb at most two such acoustic
    outliers and is marked as repaired.  Balanced mixed-speaker ranges remain
    invalid because they likely cross a real question/answer boundary.
    """

    mapped_roles = [
        role_map[str(evidence.words[pos].speaker_id)]
        for pos in positions
        if str(evidence.words[pos].speaker_id) in role_map
    ]
    counts = Counter(mapped_roles)
    if counts:
        dominant_role, dominant_count = counts.most_common(1)[0]
        minority_count = len(mapped_roles) - dominant_count
        if len(counts) > 1 and (
            dominant_count / len(mapped_roles) < 0.8 or minority_count > 2
        ):
            spans: list[str] = []
            span_start = positions.start
            current_speaker = evidence.words[span_start].speaker_id
            for pos in range(positions.start + 1, positions.stop + 1):
                speaker = (
                    evidence.words[pos].speaker_id if pos < positions.stop else object()
                )
                if speaker == current_speaker:
                    continue
                span_end = pos - 1
                mapped = role_map.get(str(current_speaker), "UNKNOWN")
                spans.append(
                    f"{evidence.words[span_start].word_id}.."
                    f"{evidence.words[span_end].word_id}={mapped}"
                )
                span_start = pos
                current_speaker = speaker
            raise TranscriptProjectionError(
                "structure_projection_invalid",
                "utterance "
                f"{raw.start_word_id}..{raw.end_word_id} crosses speaker identity; "
                f"split at acoustic spans [{', '.join(spans)}]",
            )
        if raw.role is not None and raw.role != dominant_role:
            raise TranscriptProjectionError(
                "structure_projection_invalid",
                "utterance role conflicts with diarized speaker",
            )
        has_unmapped_words = len(mapped_roles) != len(positions)
        source = (
            "speaker_map_repaired"
            if len(counts) > 1 or has_unmapped_words
            else "speaker_map"
        )
        return dominant_role, source

    if (
        raw.role in {"interviewer", "candidate"}
        and raw.confidence >= _SEMANTIC_ROLE_MIN_CONFIDENCE
    ):
        return raw.role, "semantic_recovery"
    if raw.dialogue_act not in {"noise", "closing"}:
        raise TranscriptProjectionError(
            "structure_projection_invalid",
            "acoustically unassigned substantive utterance "
            f"{raw.start_word_id}..{raw.end_word_id} requires a semantic role",
        )
    return "unknown", "unresolved"


def _split_cross_role_utterance(
    evidence: TranscriptEvidence,
    positions: range,
    role_map: dict[str, str],
    raw: _RawUtterance,
) -> list[_RawUtterance]:
    """Split a model range that spans a real interviewer/candidate boundary.

    A language model tends to keep a short answer and the interviewer's
    immediate restatement in one semantic sentence. The immutable acoustic
    roles take precedence: we split that sentence into contiguous role spans
    while preserving every source word. Tiny one- or two-word diarization
    flips remain handled by ``_resolve_utterance_role`` instead.
    """

    mapped = [role_map.get(str(evidence.words[pos].speaker_id)) for pos in positions]
    counts = Counter(role for role in mapped if role is not None)
    if len(counts) <= 1:
        return [raw]
    _dominant_role, dominant_count = counts.most_common(1)[0]
    known_count = sum(counts.values())
    if dominant_count / known_count >= 0.8 and known_count - dominant_count <= 2:
        return [raw]

    expected_role = raw.role
    if expected_role is None:
        if raw.dialogue_act == "question":
            expected_role = "interviewer"
        elif raw.dialogue_act == "answer":
            expected_role = "candidate"

    assigned: list[str | None] = []
    for offset, role in enumerate(mapped):
        if role is not None:
            assigned.append(role)
            continue
        left = next(
            (candidate for candidate in reversed(mapped[:offset]) if candidate),
            None,
        )
        right = next(
            (candidate for candidate in mapped[offset + 1 :] if candidate), None
        )
        if left == right and left is not None:
            assigned.append(left)
        elif expected_role is not None:
            assigned.append(expected_role)
        else:
            assigned.append(left or right)

    fragments: list[_RawUtterance] = []
    fragment_start = 0
    for offset in range(1, len(assigned) + 1):
        if offset < len(assigned) and assigned[offset] == assigned[fragment_start]:
            continue
        role = assigned[fragment_start]
        start_pos = positions.start + fragment_start
        end_pos = positions.start + offset - 1
        dialogue_act = raw.dialogue_act
        if dialogue_act == "question" and role == "candidate":
            dialogue_act = "answer"
        elif dialogue_act == "answer" and role == "interviewer":
            dialogue_act = "question" if fragment_start == 0 else "interruption"
        fragment_ids = {
            evidence.words[pos].word_id for pos in range(start_pos, end_pos + 1)
        }
        fragments.append(
            _RawUtterance(
                start_word_id=evidence.words[start_pos].word_id,
                end_word_id=evidence.words[end_pos].word_id,
                role=role if role in {"interviewer", "candidate"} else None,
                dialogue_act=dialogue_act,
                confidence=raw.confidence,
                punctuation=[
                    edit
                    for edit in raw.punctuation
                    if edit.after_word_id in fragment_ids
                ],
            )
        )
        fragment_start = offset
    return fragments


def _validate_window_utterances(
    evidence: TranscriptEvidence,
    *,
    envelope: _UtteranceEnvelope,
    start: int,
    end: int,
    index: dict[str, int],
    role_map: dict[str, str],
) -> list[_RawUtterance]:
    """Validate one model window before exposing any partial projection."""

    window_ids = {word.word_id for word in evidence.words[start:end]}
    occupied: set[int] = set()
    accepted: list[_RawUtterance] = []
    for model_raw in envelope.utterances:
        model_positions = _word_range(
            index, model_raw.start_word_id, model_raw.end_word_id
        )
        raw_fragments = _split_cross_role_utterance(
            evidence, model_positions, role_map, model_raw
        )
        for raw in raw_fragments:
            positions = _word_range(index, raw.start_word_id, raw.end_word_id)
            if any(pos < start or pos >= end for pos in positions):
                raise TranscriptProjectionError(
                    "structure_projection_invalid", "utterance crosses its window"
                )
            if any(pos in occupied for pos in positions):
                raise TranscriptProjectionError(
                    "structure_projection_invalid", "utterance ranges overlap"
                )
            _resolve_utterance_role(evidence, positions, role_map, raw)
            _validate_punctuation(raw.punctuation, window_ids)
            occupied.update(positions)
            accepted.append(raw)

    # Missing ranges remain explicit. Known-speaker gaps are unclassified
    # context; acoustic gaps are unresolved noise. Nothing disappears.
    cursor = start
    while cursor < end:
        if cursor in occupied:
            cursor += 1
            continue
        gap_start = cursor
        speaker = evidence.words[cursor].speaker_id
        while (
            cursor + 1 < end
            and cursor + 1 not in occupied
            and evidence.words[cursor + 1].speaker_id == speaker
        ):
            cursor += 1
        accepted.append(
            _RawUtterance(
                start_word_id=evidence.words[gap_start].word_id,
                end_word_id=evidence.words[cursor].word_id,
                dialogue_act="noise" if speaker is None else "context",
                confidence=0.0,
            )
        )
        cursor += 1
    return accepted


async def _project_utterances(
    evidence: TranscriptEvidence,
    roles: list[SpeakerRole],
    llm: LLM,
) -> list[UtteranceProjection]:
    index = evidence.word_index()
    role_map = {item.speaker_id: item.role for item in roles}
    accepted: list[_RawUtterance] = []
    for start, end in _windows(evidence):
        base_prompt = UTTERANCE_STRUCTURE_PROMPT.format(
            roles=json.dumps([item.model_dump() for item in roles], ensure_ascii=False),
            window=_window_prompt(evidence, start, end),
        )
        validation_error: TranscriptProjectionError | None = None
        for _attempt in range(3):
            repair = (
                "\n\n上一版未通过确定性校验："
                f"{validation_error.detail}。请重新返回整个 WINDOW 的 JSON；"
                "不要跨越 speaker 边界，也不要合并问题与对方回答。"
                if validation_error is not None
                else ""
            )
            response = await llm.acomplete(
                base_prompt + repair,
                response_format={"type": "json_object"},
            )
            try:
                envelope = _UtteranceEnvelope.model_validate(
                    _json_object(response.text)
                )
                window_utterances = _validate_window_utterances(
                    evidence,
                    envelope=envelope,
                    start=start,
                    end=end,
                    index=index,
                    role_map=role_map,
                )
            except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                validation_error = TranscriptProjectionError(
                    "structure_projection_invalid", str(exc)
                )
                continue
            except TranscriptProjectionError as exc:
                validation_error = exc
                continue
            accepted.extend(window_utterances)
            break
        else:
            assert validation_error is not None
            raise validation_error

    accepted.sort(key=lambda item: index[item.start_word_id])
    projections: list[UtteranceProjection] = []
    occupied_global: set[int] = set()
    for raw in accepted:
        positions = _word_range(index, raw.start_word_id, raw.end_word_id)
        if any(pos in occupied_global for pos in positions):
            raise TranscriptProjectionError(
                "structure_projection_invalid", "global utterance ranges overlap"
            )
        occupied_global.update(positions)
        speaker = evidence.words[positions.start].speaker_id
        role, role_source = _resolve_utterance_role(evidence, positions, role_map, raw)
        projections.append(
            UtteranceProjection(
                utterance_id=f"u{len(projections) + 1:04d}",
                speaker_id=speaker,
                role=role,
                role_source=role_source,
                start_word_id=raw.start_word_id,
                end_word_id=raw.end_word_id,
                dialogue_act=raw.dialogue_act,
                confidence=raw.confidence,
                punctuation=raw.punctuation,
            )
        )
    if occupied_global != set(range(len(evidence.words))):
        raise TranscriptProjectionError(
            "structure_projection_invalid", "utterances do not cover all evidence words"
        )
    return projections


def _utterance_word_ids(
    evidence: TranscriptEvidence, utterance: UtteranceProjection
) -> list[str]:
    positions = _word_range(
        evidence.word_index(), utterance.start_word_id, utterance.end_word_id
    )
    return [evidence.words[pos].word_id for pos in positions]


def _episode_prompt(
    evidence: TranscriptEvidence, utterances: list[UtteranceProjection]
) -> str:
    lines: list[str] = []
    for utterance in utterances:
        text = render_word_ids(evidence, _utterance_word_ids(evidence, utterance))
        lines.append(
            f"{utterance.utterance_id}|role={utterance.role}|"
            f"act={utterance.dialogue_act}|{text}"
        )
    return "\n".join(lines)


async def _project_episodes(
    evidence: TranscriptEvidence,
    utterances: list[UtteranceProjection],
    llm: LLM,
) -> list[_RawEpisode]:
    question_ids = {
        item.utterance_id
        for item in utterances
        if item.role == "interviewer" and item.dialogue_act == "question"
    }
    if not question_ids:
        raise TranscriptProjectionError(
            "structure_projection_invalid", "no interviewer questions were identified"
        )
    response = await llm.acomplete(
        QA_EPISODE_PROMPT.format(utterances=_episode_prompt(evidence, utterances)),
        response_format={"type": "json_object"},
    )
    try:
        envelope = _EpisodeEnvelope.model_validate(_json_object(response.text))
    except (ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise TranscriptProjectionError(
            "structure_projection_invalid", str(exc)
        ) from exc

    used: list[str] = []
    for index, episode in enumerate(envelope.episodes, start=1):
        if not set(episode.question_utterance_ids).issubset(question_ids):
            raise TranscriptProjectionError(
                "structure_projection_invalid", "episode cites a non-question utterance"
            )
        if (
            episode.parent_episode_index is not None
            and episode.parent_episode_index >= index
        ):
            raise TranscriptProjectionError(
                "structure_projection_invalid", "follow-up parent must precede child"
            )
        used.extend(episode.question_utterance_ids)
    if len(used) != len(set(used)) or set(used) != question_ids:
        raise TranscriptProjectionError(
            "structure_projection_invalid",
            "each interviewer question must belong to exactly one episode",
        )
    order = {item.utterance_id: idx for idx, item in enumerate(utterances)}
    envelope.episodes.sort(
        key=lambda episode: min(order[item] for item in episode.question_utterance_ids)
    )
    return envelope.episodes


def _punctuation_map(utterances: Sequence[UtteranceProjection]) -> dict[str, str]:
    return {
        edit.after_word_id: edit.mark
        for utterance in utterances
        for edit in utterance.punctuation
    }


def _build_qa_pairs(
    evidence: TranscriptEvidence,
    structure: TranscriptStructure,
    episodes: list[_RawEpisode],
) -> tuple[list[dict[str, Any]], ProjectionQuality]:
    utterances = structure.utterances
    utterance_by_id = {item.utterance_id: item for item in utterances}
    order = {item.utterance_id: index for index, item in enumerate(utterances)}
    punctuation = _punctuation_map(utterances)
    hidden = strict_display_hidden_words(evidence.words)
    word_map = evidence.word_map()
    candidate_substantive = {
        word_id
        for item in utterances
        if item.role == "candidate" and item.dialogue_act in {"answer", "context"}
        for word_id in _utterance_word_ids(evidence, item)
        if is_substantive_word(word_map[word_id])
    }
    substantive_words = {
        word.word_id for word in evidence.words if is_substantive_word(word)
    }
    resolved_substantive_words = {
        word_id
        for item in utterances
        if item.role in {"interviewer", "candidate"}
        for word_id in _utterance_word_ids(evidence, item)
        if word_id in substantive_words
    }
    question_words: set[str] = set()
    covered_candidate: set[str] = set()
    qa_pairs: list[dict[str, Any]] = []
    low_confidence = 0

    for episode_index, episode in enumerate(episodes, start=1):
        question_items = [
            utterance_by_id[item] for item in episode.question_utterance_ids
        ]
        question_positions = sorted(order[item.utterance_id] for item in question_items)
        start_position = min(question_positions)
        next_question_position = len(utterances)
        for later in episodes[episode_index:]:
            next_question_position = min(
                order[item] for item in later.question_utterance_ids
            )
            break

        answer_items: list[UtteranceProjection] = []
        crossings: list[str] = []
        for item in utterances[start_position + 1 : next_question_position]:
            if item.role == "candidate" and item.dialogue_act in {
                "answer",
                "context",
                "question",
            }:
                answer_items.append(item)
            elif item.role == "interviewer" and item.dialogue_act in {
                "acknowledgement",
                "interruption",
                "context",
            }:
                crossings.append(item.utterance_id)

        question_ids = [
            word_id
            for item in question_items
            for word_id in _utterance_word_ids(evidence, item)
        ]
        answer_ids = [
            word_id
            for item in answer_items
            for word_id in _utterance_word_ids(evidence, item)
        ]
        question_words.update(question_ids)
        covered_candidate.update(
            word_id for word_id in answer_ids if word_id in candidate_substantive
        )
        if not answer_ids:
            continue
        hidden_question = {word_id for word_id in question_ids if word_id in hidden}
        hidden_answer = {word_id for word_id in answer_ids if word_id in hidden}
        question = render_word_ids(
            evidence,
            question_ids,
            hidden_word_ids=hidden_question,
            punctuation_after=punctuation,
        )
        answer = render_word_ids(
            evidence,
            answer_ids,
            hidden_word_ids=hidden_answer,
            punctuation_after=punctuation,
        )
        if not question or not answer:
            continue
        confidence = min(
            [episode.confidence]
            + [item.confidence for item in question_items + answer_items]
        )
        if confidence < 0.65:
            low_confidence += 1
        timed_words = [word_map[word_id] for word_id in question_ids + answer_ids]
        starts = [word.start for word in timed_words if word.start is not None]
        ends = [word.end for word in timed_words if word.end is not None]
        qa_pairs.append(
            {
                "index": len(qa_pairs) + 1,
                "question": question,
                "answer": answer,
                "phase": episode.phase,
                "is_follow_up": episode.is_follow_up,
                "parent_index": episode.parent_episode_index,
                "source_segment_start": min(starts) if starts else None,
                "source_segment_end": max(ends) if ends else None,
                "source_provenance": {
                    "evidence_schema_version": evidence.schema_version,
                    "structure_schema_version": structure.schema_version,
                    "structure_revision": structure.revision,
                    "question_utterance_ids": episode.question_utterance_ids,
                    "answer_utterance_ids": [
                        item.utterance_id for item in answer_items
                    ],
                    "crossing_utterance_ids": crossings,
                    "question_word_ids": question_ids,
                    "answer_word_ids": answer_ids,
                    "hidden_words": [
                        {"word_id": word_id, "reason": hidden[word_id]}
                        for word_id in question_ids + answer_ids
                        if word_id in hidden
                    ],
                    "punctuation": [
                        {"after_word_id": word_id, "mark": punctuation[word_id]}
                        for word_id in question_ids + answer_ids
                        if word_id in punctuation
                    ],
                    "confidence": confidence,
                },
            }
        )

    total_words = len(evidence.words)
    aligned = sum(word.alignment_status == "aligned" for word in evidence.words)
    known = sum(word.speaker_id is not None for word in evidence.words)
    overlap = sum(word.overlap for word in evidence.words)
    candidate_coverage = (
        len(covered_candidate) / len(candidate_substantive)
        if candidate_substantive
        else 0.0
    )
    interviewer_question_words = {
        word_id
        for item in utterances
        if item.role == "interviewer" and item.dialogue_act == "question"
        for word_id in _utterance_word_ids(evidence, item)
    }
    question_coverage = (
        len(question_words & interviewer_question_words)
        / len(interviewer_question_words)
        if interviewer_question_words
        else 0.0
    )
    resolved_role_ratio = (
        len(resolved_substantive_words) / len(substantive_words)
        if substantive_words
        else 0.0
    )
    hidden_ratio = len(hidden) / total_words
    complete = (
        candidate_coverage >= 0.95
        and question_coverage == 1.0
        and aligned / total_words >= 0.98
        and resolved_role_ratio >= 0.95
        and low_confidence == 0
    )
    quality = ProjectionQuality(
        aligned_word_ratio=aligned / total_words,
        known_speaker_word_ratio=known / total_words,
        role_resolved_substantive_word_ratio=resolved_role_ratio,
        candidate_substantive_word_coverage=candidate_coverage,
        question_word_coverage=question_coverage,
        hidden_word_ratio=hidden_ratio,
        overlap_word_ratio=overlap / total_words,
        low_confidence_episode_count=low_confidence,
        status="complete" if complete else "needs_review",
    )
    return qa_pairs, quality


async def project_interview_qa(
    evidence: TranscriptEvidence,
    *,
    llm: LLM | None = None,
) -> ProjectedInterview:
    worker_llm = llm or get_internal_llm("worker")
    roles = await _infer_roles(evidence, worker_llm)
    utterances = await _project_utterances(evidence, roles, worker_llm)
    structure = TranscriptStructure(speaker_roles=roles, utterances=utterances)
    episodes = await _project_episodes(evidence, utterances, worker_llm)
    qa_pairs, quality = _build_qa_pairs(evidence, structure, episodes)
    if not qa_pairs:
        raise TranscriptProjectionError(
            "structure_projection_invalid", "no answered QA episodes were produced"
        )
    return ProjectedInterview(structure=structure, qa_pairs=qa_pairs, quality=quality)


__all__ = [
    "ProjectedInterview",
    "ProjectionQuality",
    "TranscriptProjectionError",
    "TranscriptStructure",
    "project_interview_qa",
]
