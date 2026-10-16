"""Semantic extraction must survive ASR errors without inventing source audio."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.interviews.application.recording_qa_service import (
    QAExtractionError,
    extract_recording_qa,
)
from app.media.application.transcript_evidence import build_transcript_evidence


@pytest.fixture
def evidence():
    # One incorrect acoustic label spans both roles; ASR confuses 元 with 原.
    return build_transcript_evidence(
        file_asset_id="audio",
        file_asset_version="v1",
        audio_sha256="0" * 64,
        duration_seconds=4,
        language="zh",
        asr_model="asr",
        alignment_model="align",
        diarization_model="diarize",
        raw_words=[
            {"word": text, "start": i, "end": i + 0.8}
            for i, text in enumerate(
                ["如何保存元数据？", "保存原数据。", "还有呢？", "没有商业用户。"]
            )
        ],
        regular_intervals=[{"start": 0, "end": 4, "speaker_id": "speaker_001"}],
        exclusive_intervals=[{"start": 0, "end": 4, "speaker_id": "speaker_001"}],
    )


def extraction():
    return {
        "qa": [
            {
                "question": "如何保存元数据？",
                "answer": "保存元数据。",
                "phase": "technical",
                "question_sources": [
                    {"start_word_id": "w000001", "end_word_id": "w000001"}
                ],
                "answer_sources": [
                    {"start_word_id": "w000002", "end_word_id": "w000002"}
                ],
            },
            {
                "question": "还有呢？",
                "answer": "没有商业用户。",
                "phase": "project",
                "parent_index": 1,
                "question_sources": [
                    {"start_word_id": "w000003", "end_word_id": "w000003"}
                ],
                "answer_sources": [
                    {"start_word_id": "w000004", "end_word_id": "w000004"}
                ],
            },
        ],
        "speaker_roles": [{"speaker_id": "speaker_001", "role": "unknown"}],
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_semantic_text_and_roles_can_correct_asr_while_audio_stays_unchanged(
    evidence,
):
    before = evidence.model_dump()
    llm = SimpleNamespace(
        acomplete=AsyncMock(return_value=SimpleNamespace(text=json.dumps(extraction())))
    )
    result = await extract_recording_qa(evidence, llm=llm)
    assert [item["answer"] for item in result.qa_pairs] == [
        "保存元数据。",
        "没有商业用户。",
    ]
    assert result.qa_pairs[1]["parent_index"] == 1
    assert result.qa_pairs[1]["source_segment_start"] == 2
    assert result.qa_pairs[0]["source_provenance"]["answer_word_ids"] == ["w000002"]
    assert evidence.model_dump() == before
    prompt = llm.acomplete.call_args.args[0]
    assert all(
        word.text in prompt and word.word_id in prompt for word in evidence.words
    )
    llm.acomplete.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["unknown", "reversed", "overlap", "parent", "unbacked"]
)
async def test_invalid_sources_never_publish(evidence, failure):
    data = extraction()
    qa = data["qa"][0]
    if failure == "unknown":
        qa["answer_sources"][0]["end_word_id"] = "w999999"
    elif failure == "reversed":
        qa["answer_sources"][0]["start_word_id"] = "w000004"
    elif failure == "overlap":
        qa["answer_sources"] = qa["question_sources"]
    elif failure == "parent":
        qa["parent_index"] = 2
    else:
        qa["answer_sources"] = []
    llm = SimpleNamespace(
        acomplete=AsyncMock(return_value=SimpleNamespace(text=json.dumps(data)))
    )
    with pytest.raises(QAExtractionError):
        await extract_recording_qa(evidence, llm=llm)
