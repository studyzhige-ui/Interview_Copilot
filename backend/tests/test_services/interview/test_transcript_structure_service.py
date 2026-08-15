from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.interview.transcript_structure_service import (
    TranscriptProjectionError,
    project_interview_qa,
)
from app.services.voice.transcript_evidence import build_transcript_evidence


class _FakeLLM:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = iter(payloads)
        self.prompts: list[str] = []

    async def acomplete(self, prompt: str, **_kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(
            text=json.dumps(next(self._payloads), ensure_ascii=False)
        )


def _interview_evidence():
    texts = [
        "请",
        "介绍",
        "项目",
        "情况",
        "我",
        "负责",
        "后端",
        "系统",
        "好的",
        "还",
        "优化",
        "性能",
        "为什么",
        "不用",
        "ReAct",
        "因为",
        "流程",
        "固定",
    ]
    raw = [
        {
            "word": text,
            "start": index * 0.4,
            "end": (index + 1) * 0.4,
            "score": 0.95,
        }
        for index, text in enumerate(texts)
    ]
    intervals = [
        (0.0, 1.6, "SPEAKER_00"),
        (1.6, 3.2, "SPEAKER_01"),
        (3.2, 3.6, "SPEAKER_00"),
        (3.6, 4.8, "SPEAKER_01"),
        (4.8, 6.0, "SPEAKER_00"),
        (6.0, 7.2, "SPEAKER_01"),
    ]
    tracks = [
        {"start": start, "end": end, "speaker_id": speaker}
        for start, end, speaker in intervals
    ]
    return build_transcript_evidence(
        file_asset_id="fa_audio",
        file_asset_version="v1",
        audio_sha256="1" * 64,
        duration_seconds=7.2,
        language="zh",
        asr_model="whisper",
        alignment_model="wav2vec",
        diarization_model="community-1",
        raw_words=raw,
        regular_intervals=tracks,
        exclusive_intervals=tracks,
    )


def _valid_payloads() -> list[dict]:
    return [
        {
            "speaker_roles": [
                {
                    "speaker_id": "SPEAKER_00",
                    "role": "interviewer",
                    "confidence": 0.99,
                },
                {
                    "speaker_id": "SPEAKER_01",
                    "role": "candidate",
                    "confidence": 0.99,
                },
            ]
        },
        {
            "utterances": [
                {
                    "start_word_id": "w000001",
                    "end_word_id": "w000004",
                    "dialogue_act": "question",
                    "confidence": 0.95,
                    "punctuation": [{"after_word_id": "w000004", "mark": "？"}],
                },
                {
                    "start_word_id": "w000005",
                    "end_word_id": "w000008",
                    "dialogue_act": "answer",
                    "confidence": 0.96,
                    "punctuation": [{"after_word_id": "w000008", "mark": "。"}],
                },
                {
                    "start_word_id": "w000009",
                    "end_word_id": "w000009",
                    "dialogue_act": "acknowledgement",
                    "confidence": 0.98,
                },
                {
                    "start_word_id": "w000010",
                    "end_word_id": "w000012",
                    "dialogue_act": "context",
                    "confidence": 0.95,
                    "punctuation": [{"after_word_id": "w000012", "mark": "。"}],
                },
                {
                    "start_word_id": "w000013",
                    "end_word_id": "w000015",
                    "dialogue_act": "question",
                    "confidence": 0.97,
                    "punctuation": [{"after_word_id": "w000015", "mark": "？"}],
                },
                {
                    "start_word_id": "w000016",
                    "end_word_id": "w000018",
                    "dialogue_act": "answer",
                    "confidence": 0.97,
                    "punctuation": [{"after_word_id": "w000018", "mark": "。"}],
                },
            ]
        },
        {
            "episodes": [
                {
                    "question_utterance_ids": ["u0001"],
                    "phase": "project",
                    "is_follow_up": False,
                    "parent_episode_index": None,
                    "confidence": 0.96,
                },
                {
                    "question_utterance_ids": ["u0005"],
                    "phase": "technical",
                    "is_follow_up": True,
                    "parent_episode_index": 1,
                    "confidence": 0.96,
                },
            ]
        },
    ]


def test_projection_preserves_long_answer_across_interviewer_ack() -> None:
    result = asyncio.run(
        project_interview_qa(_interview_evidence(), llm=_FakeLLM(_valid_payloads()))
    )

    assert result.quality.status == "complete"
    assert result.quality.candidate_substantive_word_coverage == 1.0
    assert [item["question"] for item in result.qa_pairs] == [
        "请介绍项目情况？",
        "为什么不用ReAct？",
    ]
    assert result.qa_pairs[0]["answer"] == "我负责后端系统。还优化性能。"
    assert result.qa_pairs[0]["source_provenance"]["crossing_utterance_ids"] == [
        "u0003"
    ]


def test_model_cannot_return_authored_question_text() -> None:
    payloads = _valid_payloads()
    payloads[1]["utterances"][0]["question"] = "被模型改写的问题"
    invalid_window = payloads[1]

    with pytest.raises(TranscriptProjectionError, match="structure_projection_invalid"):
        asyncio.run(
            project_interview_qa(
                _interview_evidence(),
                llm=_FakeLLM(
                    [payloads[0], invalid_window, invalid_window, invalid_window]
                ),
            )
        )


def test_invalid_window_is_repaired_locally_before_projection_continues() -> None:
    payloads = _valid_payloads()
    invalid_window = {
        "utterances": [
            {
                "start_word_id": "w000001",
                "end_word_id": "w000004",
                "role": None,
                "dialogue_act": "question",
                "confidence": 0.9,
                "question": "模型不得撰写正文",
            }
        ]
    }
    llm = _FakeLLM([payloads[0], invalid_window, payloads[1], payloads[2]])

    result = asyncio.run(project_interview_qa(_interview_evidence(), llm=llm))

    assert result.quality.status == "complete"
    assert "上一版未通过确定性校验" in llm.prompts[2]


def test_uncovered_diarization_words_can_be_role_recovered_without_rewriting() -> None:
    raw_words = [
        {
            "word": text,
            "start": index * 0.4,
            "end": (index + 1) * 0.4,
            "score": 0.95,
        }
        for index, text in enumerate(["请", "介绍", "我", "完整", "回答", "继续"])
    ]
    evidence = build_transcript_evidence(
        file_asset_id="fa_gap",
        file_asset_version="v1",
        audio_sha256="2" * 64,
        duration_seconds=2.4,
        language="zh",
        asr_model="whisper",
        alignment_model="wav2vec",
        diarization_model="community-1",
        raw_words=raw_words,
        regular_intervals=[
            {"start": 0.0, "end": 0.8, "speaker_id": "SPEAKER_00"},
            {"start": 2.0, "end": 2.4, "speaker_id": "SPEAKER_01"},
        ],
        exclusive_intervals=[
            {"start": 0.0, "end": 0.8, "speaker_id": "SPEAKER_00"},
            {"start": 2.0, "end": 2.4, "speaker_id": "SPEAKER_01"},
        ],
    )
    llm = _FakeLLM(
        [
            {
                "speaker_roles": [
                    {
                        "speaker_id": "SPEAKER_00",
                        "role": "interviewer",
                        "confidence": 0.99,
                    },
                    {
                        "speaker_id": "SPEAKER_01",
                        "role": "candidate",
                        "confidence": 0.99,
                    },
                ]
            },
            {
                "utterances": [
                    {
                        "start_word_id": "w000001",
                        "end_word_id": "w000002",
                        "role": None,
                        "dialogue_act": "question",
                        "confidence": 0.98,
                    },
                    {
                        "start_word_id": "w000003",
                        "end_word_id": "w000005",
                        "role": "candidate",
                        "dialogue_act": "answer",
                        "confidence": 0.96,
                    },
                    {
                        "start_word_id": "w000006",
                        "end_word_id": "w000006",
                        "role": None,
                        "dialogue_act": "context",
                        "confidence": 0.96,
                    },
                ]
            },
            {
                "episodes": [
                    {
                        "question_utterance_ids": ["u0001"],
                        "phase": "general",
                        "is_follow_up": False,
                        "parent_episode_index": None,
                        "confidence": 0.97,
                    }
                ]
            },
        ]
    )

    result = asyncio.run(project_interview_qa(evidence, llm=llm))

    assert "speaker=UNKNOWN" not in llm.prompts[0]
    assert 'REQUIRED_SPEAKERS：\n["SPEAKER_00", "SPEAKER_01"]' in llm.prompts[0]
    assert result.qa_pairs[0]["answer"] == "我完整回答继续"
    assert result.structure.utterances[1].speaker_id is None
    assert result.structure.utterances[1].role_source == "semantic_recovery"
    assert result.quality.known_speaker_word_ratio == 0.5
    assert result.quality.role_resolved_substantive_word_ratio == 1.0
    assert result.quality.status == "complete"


def test_one_word_diarization_flip_does_not_drop_source_text() -> None:
    words = ["请", "说明", "我", "完整", "保留", "所有", "原始", "回答"]
    evidence = build_transcript_evidence(
        file_asset_id="fa_flip",
        file_asset_version="v1",
        audio_sha256="3" * 64,
        duration_seconds=3.2,
        language="zh",
        asr_model="whisper",
        alignment_model="wav2vec",
        diarization_model="community-1",
        raw_words=[
            {
                "word": text,
                "start": index * 0.4,
                "end": (index + 1) * 0.4,
                "score": 0.95,
            }
            for index, text in enumerate(words)
        ],
        regular_intervals=[
            {"start": 0.0, "end": 0.8, "speaker_id": "SPEAKER_00"},
            {"start": 0.8, "end": 1.6, "speaker_id": "SPEAKER_01"},
            {"start": 1.6, "end": 2.0, "speaker_id": "SPEAKER_00"},
            {"start": 2.0, "end": 3.2, "speaker_id": "SPEAKER_01"},
        ],
        exclusive_intervals=[
            {"start": 0.0, "end": 0.8, "speaker_id": "SPEAKER_00"},
            {"start": 0.8, "end": 1.6, "speaker_id": "SPEAKER_01"},
            {"start": 1.6, "end": 2.0, "speaker_id": "SPEAKER_00"},
            {"start": 2.0, "end": 3.2, "speaker_id": "SPEAKER_01"},
        ],
    )
    llm = _FakeLLM(
        [
            {
                "speaker_roles": [
                    {
                        "speaker_id": "SPEAKER_00",
                        "role": "interviewer",
                        "confidence": 0.99,
                    },
                    {
                        "speaker_id": "SPEAKER_01",
                        "role": "candidate",
                        "confidence": 0.99,
                    },
                ]
            },
            {
                "utterances": [
                    {
                        "start_word_id": "w000001",
                        "end_word_id": "w000002",
                        "role": None,
                        "dialogue_act": "question",
                        "confidence": 0.98,
                    },
                    {
                        "start_word_id": "w000003",
                        "end_word_id": "w000008",
                        "role": None,
                        "dialogue_act": "answer",
                        "confidence": 0.97,
                    },
                ]
            },
            {
                "episodes": [
                    {
                        "question_utterance_ids": ["u0001"],
                        "phase": "general",
                        "is_follow_up": False,
                        "parent_episode_index": None,
                        "confidence": 0.97,
                    }
                ]
            },
        ]
    )

    result = asyncio.run(project_interview_qa(evidence, llm=llm))

    assert result.qa_pairs[0]["answer"] == "我完整保留所有原始回答"
    assert result.structure.utterances[1].role_source == "speaker_map_repaired"
