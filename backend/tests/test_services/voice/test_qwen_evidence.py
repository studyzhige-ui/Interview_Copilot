"""Long-recording mechanics with deterministic observations, not model quality."""

from array import array
from dataclasses import replace
import math
import sys

import pytest

from app.local_inference.audio import MAX_PCM_BYTES, SAMPLE_RATE, _lexical
from app.media.application import qwen_evidence as pipeline
from app.media.application.evidence_stitching import (
    restore_word_layout,
    stitch_boundary,
)
from app.media.application.evidence_windows import evidence_windows
from app.media.application.qwen_evidence import StageModels, collect_qwen_parts
from app.media.application.speaker_identity import SpeakerIdentity


async def blocks_for(seconds):
    for start in range(0, seconds, 30):
        # Seconds encoded in samples let the fake identify context offsets.
        block = array("h")
        for second in range(start, min(start + 30, seconds)):
            block.extend([second + 1] * SAMPLE_RATE)
        if sys.byteorder != "little":
            block.byteswap()
        yield block.tobytes()


def word(text, start, end):
    return {"text": text, "start": start, "end": end}


def voice(label, embedding):
    return {"speaker_id": label, "embedding": embedding}


class Stages:
    models = StageModels("test-asr@1", "test-align@2", "test-diarization@3")

    def __init__(self, words=None):
        self.words = (
            words
            if words is not None
            else [
                ("你好，", 1.0, 1.4, "A"),
                ("Hello", 25.5, 25.9, "A"),
                ("world!", 26.1, 26.5, "B"),
                ("再见。", 50.0, 50.8, "A"),
            ]
        )
        self.calls = []
        self.completed_calls = 0

    async def call(self, role, pcm, *, text="", language=None):
        start = int.from_bytes(pcm[:2], "little", signed=True) - 1
        duration = len(pcm) / (SAMPLE_RATE * 2)
        self.calls.append((role, start, len(pcm)))
        self.completed_calls += 1
        rows = [
            row for row in self.words if start <= row[1] and row[2] <= start + duration
        ]
        if role == "transcription":
            return {
                "text": " ".join(row[0] for row in rows),
                "language": "Chinese",
                "words": [],
            }
        if role == "alignment":
            return {
                "text": text,
                "language": language,
                "words": [
                    word(_lexical(row[0]), row[1] - start, row[2] - start)
                    for row in rows
                ],
            }
        assert role == "diarization"
        labels = (
            {"A": "local_0", "B": "local_1"}
            if not start
            else {"A": "local_1", "B": "local_0"}
        )
        tracks = [
            {
                "start": row[1] - start,
                "end": row[2] - start,
                "speaker_id": labels[row[3]],
            }
            for row in rows
        ]
        present = dict.fromkeys(row[3] for row in rows)
        return {
            "regular": tracks,
            "exclusive": [dict(row) for row in tracks],
            "speakers": [
                voice(labels[speaker], [1.0, 0.0] if speaker == "A" else [0.0, 1.0])
                for speaker in present
            ],
        }


@pytest.mark.asyncio
async def test_core_partition_is_sample_exact_and_context_is_bounded():
    # One finite-domain test; all boundary values remain explicitly exercised.
    for seconds in (1, 25, 26, 27, 28, 30, 52, 53, 59, 60, 78, 91):
        result = [
            item
            async for item in evidence_windows(
                blocks_for(seconds), max_samples=seconds * SAMPLE_RATE
            )
        ]
        cursor = 0
        for item in result:
            assert item.core_start == cursor
            assert item.start <= item.core_start < item.core_end <= item.end
            assert len(item.pcm) <= MAX_PCM_BYTES
            assert (
                int.from_bytes(item.pcm[:2], "little", signed=True)
                == item.start // SAMPLE_RATE + 1
            )
            cursor = item.core_end
        assert cursor == seconds * SAMPLE_RATE


@pytest.mark.asyncio
async def test_decoder_backpressure_does_not_read_the_entire_recording():
    reads = 0

    async def source():
        nonlocal reads
        async for block in blocks_for(300):
            reads += 1
            yield block

    windows = evidence_windows(source(), max_samples=300 * SAMPLE_RATE)
    first = await anext(windows)
    assert first.core_start == 0 and reads == 1
    await windows.aclose()
    assert reads == 1


@pytest.mark.asyncio
async def test_input_block_and_recording_limits_fail_not_truncate():
    async def one(value):
        yield value

    for value in (b"", b"x", bytearray(b"xx"), b"x" * (MAX_PCM_BYTES + 2)):
        with pytest.raises(ValueError, match="pcm_block"):
            [item async for item in evidence_windows(one(value), max_samples=1_000_000)]
    with pytest.raises(ValueError, match="duration_exceeds_limit"):
        [
            item
            async for item in evidence_windows(
                blocks_for(30), max_samples=29 * SAMPLE_RATE
            )
        ]
    for limit in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="sample_limit"):
            [item async for item in evidence_windows(one(b"xx"), max_samples=limit)]


def test_original_spacing_punctuation_and_fullwidth_text_are_preserved():
    for text, pieces in (
        ("你好，世界！", ["你好", "世界"]),
        ("  Hello, world!\n", ["Hello", "world"]),
        ("Ｃ＋＋ 与 API-v2。", ["C++", "与", "APIv2"]),
    ):
        aligned = [word(piece, i, i + 0.5) for i, piece in enumerate(pieces)]
        result = restore_word_layout(text, aligned, 24)
        assert "".join(item["text"] for item in result) == text
        assert result[0]["start"] == 24
    with pytest.raises(ValueError, match="alignment_missing"):
        restore_word_layout("hi", [word("hi", None, None)], 0)
    with pytest.raises(ValueError, match="coverage_mismatch"):
        restore_word_layout("actual", [word("invented", 0, 1)], 0)
    with pytest.raises(ValueError, match="unicode_layout_ambiguous"):
        restore_word_layout("ﬃ", [word("f", 0, 1), word("fi", 1, 2)], 0)


def test_overlap_anchor_does_not_delete_real_repeated_words():
    left = [word("go ", 25, 25.2), word("go!", 26, 26.2)]
    right = [
        word("go ", 25.02, 25.22),
        word("go! ", 26.02, 26.22),
        word("now", 27, 27.2),
    ]
    done, pending = stitch_boundary(
        left, right, boundary=26, overlap_start=24, overlap_end=28
    )
    assert [_lexical(item["text"]) for item in done + pending] == ["go", "go", "now"]


def test_silence_seam_and_ambiguous_boundary_are_distinct():
    left, right = [word("before", 20, 21)], [word("after", 30, 31)]
    assert stitch_boundary(
        left, right, boundary=26, overlap_start=24, overlap_end=28
    ) == (left, right)
    with pytest.raises(ValueError, match="boundary_ambiguous"):
        stitch_boundary(
            [word("old", 25, 26)],
            [word("new", 25, 26)],
            boundary=26,
            overlap_start=24,
            overlap_end=28,
        )
    with pytest.raises(ValueError, match="boundary_capacity"):
        stitch_boundary(
            [word("a", 25, 26)] * 129, [], boundary=26, overlap_start=24, overlap_end=28
        )


def test_speaker_labels_can_swap_but_recording_identity_cannot():
    matcher = SpeakerIdentity()
    first = matcher.assign([voice("local_0", [1, 0]), voice("local_1", [0, 1])])
    later = matcher.assign([voice("local_0", [0, 2]), voice("local_1", [3, 0])])
    assert later["local_0"] == first["local_1"]
    assert later["local_1"] == first["local_0"]
    assert set(later.values()) == {"speaker_001", "speaker_002"}


def test_ambiguous_speaker_match_is_atomic_and_never_a_new_certain_identity():
    matcher = SpeakerIdentity()
    matcher.assign([voice("a", [1, 0]), voice("b", [0, 1])])
    with pytest.raises(ValueError, match="identity_ambiguous"):
        matcher.assign([voice("new", [-1, 0]), voice("uncertain", [1, 1])])
    assert matcher.assign([voice("new", [-1, 0])]) == {"new": "speaker_003"}
    with pytest.raises(ValueError, match="identity_ambiguous"):
        matcher.assign([voice("a", [1, 0]), voice("b", [1, 0])])
    with pytest.raises(ValueError, match="dimension_changed"):
        matcher.assign([voice("a", [1, 0, 0])])


def test_speaker_anchor_does_not_drift_and_capacity_is_enforced():
    matcher = SpeakerIdentity(max_speakers=2)
    matcher.assign([voice("a", [1, 0])])
    angle = math.radians(30)
    matcher.assign([voice("renamed", [math.cos(angle), math.sin(angle)])])
    with pytest.raises(ValueError, match="identity_ambiguous"):
        matcher.assign([voice("drift", [math.cos(2 * angle), math.sin(2 * angle)])])
    matcher.assign([voice("b", [0, -1])])
    with pytest.raises(ValueError, match="speaker_capacity"):
        matcher.assign([voice("c", [-1, 0])])


@pytest.mark.asyncio
async def test_long_form_has_exact_duration_one_copy_per_word_and_global_speakers():
    stages = Stages()
    parts = await collect_qwen_parts(
        blocks_for(60), stages, max_samples=60 * SAMPLE_RATE
    )
    assert parts.complete is True
    assert parts.transcript.duration_seconds == 60
    assert [_lexical(item["text"]) for item in parts.transcript.words] == [
        "你好",
        "Hello",
        "world",
        "再见",
    ]
    assert [item["start"] for item in parts.transcript.words] == [1, 25.5, 26.1, 50]
    assert [row["speaker_id"] for row in parts.speakers.exclusive] == [
        "speaker_001",
        "speaker_001",
        "speaker_002",
        "speaker_001",
    ]
    assert all(size <= MAX_PCM_BYTES for _, _, size in stages.calls)
    assert {offset for _, offset, _ in stages.calls} == {0, 24, 50}
    assert parts.transcript.asr_model == "test-asr@1"
    assert parts.transcript.alignment_model == "test-align@2"
    assert parts.speakers.model == "test-diarization@3"


@pytest.mark.asyncio
async def test_late_decoder_failure_never_returns_complete_parts_or_retries():
    stages = Stages()

    async def broken():
        source = blocks_for(30)
        yield await anext(source)
        raise ValueError("decoder_broke_after_first_window")

    with pytest.raises(ValueError, match="decoder_broke"):
        await collect_qwen_parts(broken(), stages, max_samples=60 * SAMPLE_RATE)
    assert len(stages.calls) == 3


@pytest.mark.asyncio
async def test_missing_alignment_and_speaker_output_cannot_publish(monkeypatch):
    for defect in ("alignment", "diarization"):
        stages = Stages()
        original = stages.call

        async def broken(role, pcm, **kwargs):
            value = await original(role, pcm, **kwargs)
            if role == defect:
                if role == "alignment":
                    value["words"][0].update(start=None, end=None)
                else:
                    value = {"regular": [], "exclusive": [], "speakers": []}
            return value

        monkeypatch.setattr(stages, "call", broken)
        with pytest.raises(ValueError, match="alignment_missing|without_speaker"):
            await collect_qwen_parts(
                blocks_for(28), stages, max_samples=28 * SAMPLE_RATE
            )


@pytest.mark.asyncio
async def test_empty_recording_is_not_fabricated_single_speaker_success():
    stages = Stages(words=[])
    with pytest.raises(ValueError, match="no_transcribed_speech"):
        await collect_qwen_parts(blocks_for(1), stages, max_samples=SAMPLE_RATE)
    assert [role for role, _, _ in stages.calls] == ["transcription", "diarization"]


@pytest.mark.asyncio
async def test_output_budget_and_model_identity_cannot_change_mid_recording(
    monkeypatch,
):
    monkeypatch.setattr(pipeline, "MAX_WORDS", 1)
    with pytest.raises(ValueError, match="evidence_capacity"):
        await collect_qwen_parts(blocks_for(60), Stages(), max_samples=60 * SAMPLE_RATE)
    monkeypatch.setattr(pipeline, "MAX_WORDS", 200_000)
    stages = Stages()
    original = stages.call

    async def changed(role, pcm, **kwargs):
        value = await original(role, pcm, **kwargs)
        stages.models = replace(stages.models, asr="different")
        return value

    monkeypatch.setattr(stages, "call", changed)
    with pytest.raises(ValueError, match="model_identity_changed"):
        await collect_qwen_parts(blocks_for(28), stages, max_samples=28 * SAMPLE_RATE)


def test_boundary_keeps_separator_from_the_continuing_asr_observation():
    left = restore_word_layout("Hello", [word("Hello", 25, 25.5)], 0)
    right = restore_word_layout(
        "Hello world!", [word("Hello", 1, 1.5), word("world", 3, 3.5)], 24
    )
    done, pending = stitch_boundary(
        left, right, boundary=26, overlap_start=24, overlap_end=28
    )
    assert "".join(row["text"] for row in done + pending) == "Hello world!"


@pytest.mark.asyncio
async def test_reblocking_does_not_require_decoder_block_boundaries_to_align():
    async def source():
        for _ in range(37):
            yield b"\x01\x00" * 12345

    total = 37 * 12345
    windows = [w async for w in evidence_windows(source(), max_samples=total)]
    assert windows[-1].core_end == total
    assert sum(w.core_end - w.core_start for w in windows) == total
    assert all(w.pcm == b"\x01\x00" * (w.end - w.start) for w in windows)


@pytest.mark.asyncio
async def test_recording_language_does_not_claim_one_language_when_chunks_differ(
    monkeypatch,
):
    stages = Stages()
    original = stages.call

    async def multilingual(role, pcm, **kwargs):
        value = await original(role, pcm, **kwargs)
        if role == "transcription" and int.from_bytes(pcm[:2], "little") > 1:
            value["language"] = "English"
        return value

    monkeypatch.setattr(stages, "call", multilingual)
    result = await collect_qwen_parts(
        blocks_for(60), stages, max_samples=60 * SAMPLE_RATE
    )
    assert result.transcript.language is None


@pytest.mark.asyncio
async def test_cancellation_stops_new_model_calls(monkeypatch):
    import asyncio

    stages = Stages()
    original = stages.call

    async def cancelled(role, pcm, **kwargs):
        if role == "diarization":
            raise asyncio.CancelledError
        return await original(role, pcm, **kwargs)

    monkeypatch.setattr(stages, "call", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await collect_qwen_parts(blocks_for(60), stages, max_samples=60 * SAMPLE_RATE)
    assert len(stages.calls) == 1


@pytest.mark.asyncio
async def test_unrecognized_speech_is_not_silently_reported_as_silence(monkeypatch):
    stages = Stages()
    original = stages.call

    async def dropped(role, pcm, **kwargs):
        value = await original(role, pcm, **kwargs)
        if role == "transcription":
            value["text"] = ""
        return value

    monkeypatch.setattr(stages, "call", dropped)
    with pytest.raises(ValueError, match="speech_without_text"):
        await collect_qwen_parts(blocks_for(28), stages, max_samples=28 * SAMPLE_RATE)


@pytest.mark.asyncio
async def test_recording_rejects_empty_language_and_track_capacity(monkeypatch):
    stages = Stages()
    original = stages.call

    async def missing(role, pcm, **kwargs):
        value = await original(role, pcm, **kwargs)
        if role == "transcription":
            value["language"] = ""
        return value

    monkeypatch.setattr(stages, "call", missing)
    with pytest.raises(ValueError, match="language_missing"):
        await collect_qwen_parts(blocks_for(28), stages, max_samples=28 * SAMPLE_RATE)
    monkeypatch.setattr(pipeline, "MAX_TRACKS", 1)
    with pytest.raises(ValueError, match="track_capacity"):
        await collect_qwen_parts(blocks_for(28), Stages(), max_samples=28 * SAMPLE_RATE)


def test_speaker_policy_and_vectors_fail_without_numeric_coercion():
    for kwargs in (
        {"match_threshold": True},
        {"margin": 0},
        {"max_speakers": True},
        {"new_threshold": 0.9},
        {"match_threshold": float("nan")},
    ):
        with pytest.raises(ValueError, match="identity_policy"):
            SpeakerIdentity(**kwargs)
    for vector in ([True], ["1"], [float("inf")], [float("nan")], [10**500], [0], []):
        with pytest.raises(ValueError, match="speaker_embedding"):
            SpeakerIdentity().assign([voice("x", vector)])


@pytest.mark.asyncio
async def test_real_overlapping_speech_tracks_survive_core_clipping(monkeypatch):
    stages = Stages()
    original = stages.call

    async def overlap(role, pcm, **kwargs):
        result = await original(role, pcm, **kwargs)
        start = int.from_bytes(pcm[:2], "little") - 1
        if role == "diarization" and start in (0, 24):
            a, b = ("local_0", "local_1") if start == 0 else ("local_1", "local_0")
            result["regular"] = [
                {"start": 25.5 - start, "end": 26.5 - start, "speaker_id": a},
                {"start": 25.8 - start, "end": 26.8 - start, "speaker_id": b},
            ] + [row for row in result["regular"] if row["start"] + start > 30]
        return result

    monkeypatch.setattr(stages, "call", overlap)
    result = await collect_qwen_parts(
        blocks_for(60), stages, max_samples=60 * SAMPLE_RATE
    )
    intervals = result.speakers.regular
    assert any(
        a["speaker_id"] != b["speaker_id"]
        and max(a["start"], b["start"]) < min(a["end"], b["end"])
        for a in intervals
        for b in intervals
    )
    assert all(
        a["end"] <= b["start"]
        for a, b in zip(result.speakers.exclusive, result.speakers.exclusive[1:])
    )


@pytest.mark.asyncio
async def test_real_ffmpeg_recording_decode_to_complete_parts_and_child_cleanup(
    tmp_path,
):
    import wave
    from app.media.application.pcm_stream import PCMStream

    path = tmp_path / "recording.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        async for block in blocks_for(60):
            audio.writeframes(block)
    async with PCMStream(
        str(path), max_bytes=path.stat().st_size, max_ms=60_000
    ) as source:
        result = await collect_qwen_parts(
            source, Stages(), max_samples=60 * SAMPLE_RATE
        )
        assert source.complete
    assert result.complete and result.transcript.duration_seconds == 60
    assert source.fd is None and source.process.returncode is not None
    assert len(result.transcript.words) == 4


@pytest.mark.asyncio
async def test_real_ffmpeg_is_reaped_when_model_stage_fails(tmp_path):
    import wave
    from app.media.application.pcm_stream import PCMStream

    path = tmp_path / "recording.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        async for block in blocks_for(60):
            audio.writeframes(block)

    class Failed(Stages):
        async def call(self, *args, **kwargs):
            raise RuntimeError("model_stage_failure")

    source = PCMStream(str(path), max_bytes=path.stat().st_size, max_ms=60_000)
    with pytest.raises(RuntimeError, match="model_stage_failure"):
        async with source:
            await collect_qwen_parts(source, Failed(), max_samples=60 * SAMPLE_RATE)
    assert source.fd is None and source.process.returncode is not None
