from __future__ import annotations

from app.services.voice.transcript_evidence import (
    build_transcript_evidence,
    render_raw_turns,
    render_word_ids,
    strict_display_hidden_words,
)


def _evidence():
    return build_transcript_evidence(
        file_asset_id="fa_audio",
        file_asset_version="v1",
        audio_sha256="0" * 64,
        duration_seconds=3.0,
        language="zh",
        asr_model="whisper",
        alignment_model="wav2vec",
        diarization_model="community-1",
        raw_words=[
            {"word": "嗯", "start": 0.0, "end": 0.2, "score": 0.9},
            {"word": "我", "start": 0.2, "end": 0.4, "score": 0.9},
            {"word": "我", "start": 0.42, "end": 0.6, "score": 0.9},
            {"word": "负责", "start": 0.6, "end": 1.0, "score": 0.9},
            {"word": "系统", "start": 1.0, "end": 1.4, "score": 0.9},
            {"word": "好的", "start": 1.5, "end": 1.8, "score": 0.9},
        ],
        regular_intervals=[
            {"start": 0.0, "end": 1.6, "speaker_id": "SPEAKER_01"},
            {"start": 1.45, "end": 1.8, "speaker_id": "SPEAKER_00"},
        ],
        exclusive_intervals=[
            {"start": 0.0, "end": 1.45, "speaker_id": "SPEAKER_01"},
            {"start": 1.45, "end": 1.8, "speaker_id": "SPEAKER_00"},
        ],
    )


def test_evidence_keeps_words_and_separates_overlap_from_primary_speaker() -> None:
    evidence = _evidence()

    assert [word.text for word in evidence.words] == [
        "嗯",
        "我",
        "我",
        "负责",
        "系统",
        "好的",
    ]
    assert evidence.words[4].speaker_id == "SPEAKER_01"
    assert evidence.words[5].speaker_id == "SPEAKER_00"
    assert evidence.words[5].overlap is True
    assert [turn.speaker_id for turn in evidence.acoustic_turns] == [
        "SPEAKER_01",
        "SPEAKER_00",
    ]
    assert "负责系统" in render_raw_turns(evidence)


def test_display_cleanup_only_hides_audited_filler_and_exact_stutter() -> None:
    evidence = _evidence()
    hidden = strict_display_hidden_words(evidence.words)
    ids = [word.word_id for word in evidence.words[:5]]

    assert hidden == {
        "w000001": "filled_pause_or_noise",
        "w000003": "immediate_exact_repetition",
    }
    assert render_word_ids(evidence, ids, hidden_word_ids=set(hidden)) == "我负责系统"
    assert render_word_ids(evidence, ids) == "嗯我我负责系统"
