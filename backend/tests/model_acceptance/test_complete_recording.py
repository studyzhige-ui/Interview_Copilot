"""Opt-in real WhisperX + isolated Community-1 acceptance; no provider mocks."""

import asyncio
import difflib
import json
import os
import sys
import time
from pathlib import Path
import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["real-synthetic.wav", "two-speaker-separate.wav"])
async def test_complete_recording_through_the_real_broker(tmp_path, filename):
    fixture = os.environ.get("IC_REAL_RECORDING_DIR")
    if not fixture:
        pytest.skip("explicit original recording and offline model assets required")
    import torch
    from app.core.config import settings
    from app.core.hf_runtime import resolve_local_snapshot
    from app.local_inference.config import BrokerConfig, ModelSpec
    from app.local_inference.server import Server
    from app.media.application import whisperx_engine as engine
    from app.media.application.evidence_source import capture_evidence_source
    from app.media.application.evidence_pipeline import compose_transcript_evidence
    from app.media.application.evidence_stitching import _lexical

    torch.set_num_threads(4)
    root = Path(fixture)
    if not (root / filename).is_file():
        pytest.skip(f"explicit recording fixture required: {filename}")
    spec = ModelSpec(
        "diarization",
        settings.DIARIZATION_MODEL_ID,
        resolve_local_snapshot(settings.DIARIZATION_MODEL_ID),
        sys.executable,
        revision=settings.MODEL_REVISIONS_JSON.get(settings.DIARIZATION_MODEL_ID),
        dimension=1,
        max_tokens=4096,
    )
    server = Server(
        BrokerConfig(settings.LOCAL_INFERENCE_SOCKET, str(tmp_path / "cache"), (spec,))
    )
    started = time.monotonic()
    await server.start()
    try:
        await asyncio.to_thread(engine.init_whisper_model)
        with capture_evidence_source(
            str(root / filename),
            file_asset_id="acceptance",
            file_asset_version="original",
            max_bytes=settings.USAGE_AUDIO_MAX_BYTES,
        ) as source:
            parts = await asyncio.to_thread(
                engine.collect_interview_evidence_sync,
                source.path,
                model=settings.TRANSCRIPTION_MODEL,
                language="zh",
            )
            evidence = compose_transcript_evidence(
                source, parts, max_duration_ms=settings.USAGE_AUDIO_MAX_MS
            )
        # Persist the actual evidence even when a regression assertion fails.
        (root / f"{Path(filename).stem}-evidence.json").write_text(
            evidence.model_dump_json(indent=2), encoding="utf-8"
        )
        if filename == "two-speaker-separate.wav":
            turns = json.loads(
                (root / "interview-reference.json").read_text(encoding="utf-8")
            )
            labels = []
            for turn in turns:
                observed = {
                    word.speaker_id
                    for word in evidence.words
                    if word.start is not None
                    and word.end is not None
                    and turn["start"] <= (word.start + word.end) / 2 <= turn["end"]
                    and _lexical(word.text)
                }
                assert len(observed) == 1 and None not in observed
                labels.append(next(iter(observed)))
            assert len(labels) == 4
            assert (
                labels[0] == labels[2]
                and labels[1] == labels[3]
                and labels[0] != labels[1]
            )
            assert parts.complete and evidence.audio.duration_seconds == pytest.approx(
                122.56870748, abs=0.001
            )
            return
        reference = _lexical((root / "reference.txt").read_text(encoding="utf-8"))
        actual = _lexical("".join(w.text for w in evidence.words))
        assert (
            evidence.audio.sha256
            == "969e90d75a1717934eab076d3357004b07f2d2e678bd8ffda45b14d1b6fe8502"
        )
        assert evidence.audio.duration_seconds == 121.617375 and parts.complete
        assert len(actual) == len(reference) == 393
        changes = [
            op
            for op in difflib.SequenceMatcher(
                None, reference, actual, autojunk=False
            ).get_opcodes()
            if op[0] != "equal"
        ]
        assert all(
            kind == "replace" and b - a == d - c == 1 for kind, a, b, c, d in changes
        )
        assert len(changes) <= 2
        assert {w.speaker_id for w in evidence.words if w.speaker_id} == {"speaker_001"}
        letters = [w for w in evidence.words for _ in _lexical(w.text)]
        for phrase, lower, upper in [
            ("遇到不确定的边界", 58, 61),
            ("同一个说话人在暂停之后再次出现", 70, 75),
            ("现在这段合成录音结束", 116, 120),
        ]:
            assert actual.count(phrase) == 1
            at = actual.index(phrase)
            assert (
                lower <= letters[at].start < letters[at + len(phrase) - 1].end <= upper
            )
        snapshot = server.broker.snapshot()
        # Six observations, one global clustering, six bounded reconstructions.
        assert snapshot["completed"] == 13
        assert snapshot["rejected"] == snapshot["unknown"] == snapshot["pending"] == 0
        assert not snapshot["active"] and not snapshot["faulted"]
        report = {
            "duration": evidence.audio.duration_seconds,
            "characters": len(actual),
            "changes": changes,
            "broker": snapshot,
            "seconds": time.monotonic() - started,
        }
        (root / "broker-validation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        await server.close()
