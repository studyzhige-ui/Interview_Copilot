"""Recording mechanics shared by the active WhisperX evidence collector."""

from array import array
from functools import partial
from types import SimpleNamespace
import math
import sys
import pytest
from app.local_inference.audio import SAMPLE_RATE, MAX_PCM_BYTES
from app.media.application.evidence_stitching import (
    restore_word_layout,
)
from app.media.application.evidence_windows import evidence_windows as stream_windows
from app.media.application.speaker_identity import SpeakerIdentity

evidence_windows = partial(stream_windows, choose_end=lambda pcm, start, limit: limit)


@pytest.mark.asyncio
async def test_adaptive_cores_preserve_every_sample_once_including_fractional_tail():
    source = b"".join([block async for block in blocks_for(91)]) + b"\x01\x02" * 17

    async def blocks():
        for start in range(0, len(source), MAX_PCM_BYTES):
            yield source[start : start + MAX_PCM_BYTES]

    windows = [
        w
        async for w in stream_windows(
            blocks(),
            max_samples=len(source) // 2,
            choose_end=lambda pcm, start, limit: min(
                limit, start + 13 * SAMPLE_RATE + 17
            ),
        )
    ]
    cores = []
    cursor = 0
    for window in windows:
        assert window.core_start == cursor
        assert len(window.pcm) <= MAX_PCM_BYTES
        cores.append(
            window.pcm[
                2 * (window.core_start - window.start) : 2
                * (window.core_end - window.start)
            ]
        )
        cursor = window.core_end
    assert b"".join(cores) == source
    assert cursor == len(source) // 2
    assert len(windows[-1].pcm) == MAX_PCM_BYTES
    assert windows[-1].core_end - windows[-1].core_start <= 26 * SAMPLE_RATE


@pytest.mark.asyncio
async def test_short_tail_has_full_speaker_context_but_only_its_own_asr_core():
    windows = [
        w async for w in evidence_windows(blocks_for(80), max_samples=80 * SAMPLE_RATE)
    ]
    tail = windows[-1]
    assert (tail.start, tail.core_start, tail.core_end) == (
        50 * SAMPLE_RATE,
        78 * SAMPLE_RATE,
        80 * SAMPLE_RATE,
    )
    assert len(tail.pcm) == MAX_PCM_BYTES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "choose", [lambda s, e: s, lambda s, e: e + 1, lambda s, e: True]
)
async def test_bad_adaptive_boundary_cannot_skip_or_repeat_samples(choose):
    with pytest.raises(ValueError, match="core_boundary"):
        [
            w
            async for w in stream_windows(
                blocks_for(60),
                max_samples=60 * SAMPLE_RATE,
                choose_end=lambda pcm, start, limit: choose(start, limit),
            )
        ]


@pytest.mark.parametrize(
    "spans,expected",
    [
        ([(0.03, 7.8), (8.5, 16.6), (17.3, 19.6), (20.3, 29.96)], 19.95),
        ([(0.03, 15), (15, 29.96)], 15),
        ([(5, 29.96)], 5),
        ([(0.03, 25), (29, 29.96)], 28),
        ([], 28),
    ],
)
def test_vad_boundary_keeps_utterances_whole_and_supports_min_cut(
    monkeypatch, spans, expected
):
    from app.media.application import whisperx_engine as engine

    class Vad:
        def preprocess_audio(self, audio):
            return audio

        def __call__(self, payload):
            assert len(payload["waveform"]) == 30 * SAMPLE_RATE
            return object()

        def merge_chunks(self, scores, duration, **kwargs):
            return [{"segments": spans}] if spans else []

    monkeypatch.setattr(
        engine,
        "whisper_model",
        SimpleNamespace(
            vad_model=Vad(),
            _vad_params={"vad_onset": 0.5, "vad_offset": 0.363},
        ),
    )
    boundary = engine._speech_core_end(
        b"\0\0" * 30 * SAMPLE_RATE, 2 * SAMPLE_RATE, 28 * SAMPLE_RATE
    )
    assert abs(boundary / SAMPLE_RATE - expected) <= 1 / SAMPLE_RATE


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
    assert restore_word_layout("hi", [word("hi", None, None)], 0)[0]["start"] is None
    with pytest.raises(ValueError, match="coverage_mismatch"):
        restore_word_layout("actual", [word("invented", 0, 1)], 0)
    with pytest.raises(ValueError, match="unicode_layout_ambiguous"):
        restore_word_layout("ﬃ", [word("f", 0, 1), word("fi", 1, 2)], 0)


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
async def test_reblocking_does_not_require_decoder_block_boundaries_to_align():
    async def source():
        for _ in range(37):
            yield b"\x01\x00" * 12345

    total = 37 * 12345
    windows = [w async for w in evidence_windows(source(), max_samples=total)]
    assert windows[-1].core_end == total
    assert sum(w.core_end - w.core_start for w in windows) == total
    assert all(w.pcm == b"\x01\x00" * (w.end - w.start) for w in windows)


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
