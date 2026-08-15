"""Word-level speaker rendering for the local WhisperX pipeline."""

import os
from types import SimpleNamespace

from app.services.voice import whisperx_engine
from app.services.voice.whisperx_engine import _segments_to_markdown


def test_ffmpeg_resolver_uses_conda_library_bin(monkeypatch, tmp_path):
    conda_prefix = tmp_path / "conda-env"
    binary_dir = conda_prefix / "Library" / "bin"
    binary_dir.mkdir(parents=True)
    binary = binary_dir / "ffmpeg.exe"
    binary.touch()
    monkeypatch.setattr(whisperx_engine.shutil, "which", lambda _name: None)
    monkeypatch.setattr(whisperx_engine.sys, "prefix", str(tmp_path / "other"))
    monkeypatch.setenv("CONDA_PREFIX", str(conda_prefix))
    monkeypatch.setenv("PATH", "existing-path")

    assert whisperx_engine._ensure_ffmpeg_available() == str(binary.resolve())
    assert os.environ["PATH"].split(os.pathsep)[0] == str(binary_dir.resolve())


def test_ffmpeg_resolver_fails_with_deployment_error(monkeypatch, tmp_path):
    monkeypatch.setattr(whisperx_engine.shutil, "which", lambda _name: None)
    monkeypatch.setattr(whisperx_engine.sys, "prefix", str(tmp_path / "missing"))
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    try:
        whisperx_engine._ensure_ffmpeg_available()
    except RuntimeError as exc:
        assert str(exc).startswith("ffmpeg_unavailable:")
    else:
        raise AssertionError("missing FFmpeg must fail before transcription")


def test_word_level_speakers_split_dialogue_inside_one_asr_segment():
    rendered = _segments_to_markdown(
        [
            {
                "speaker": "SPEAKER_01",
                "text": "你用什么模型 WhisperX 是本地部署的",
                "words": [
                    {"word": "你用什么模型", "speaker": "SPEAKER_01"},
                    {"word": " WhisperX", "speaker": "SPEAKER_00"},
                    {"word": " 是本地还是 API", "speaker": "SPEAKER_01"},
                    {"word": " 本地部署的", "speaker": "SPEAKER_00"},
                ],
            }
        ]
    )

    assert rendered == (
        "**[SPEAKER_01]**: 你用什么模型\n\n"
        "**[SPEAKER_00]**: WhisperX\n\n"
        "**[SPEAKER_01]**: 是本地还是 API\n\n"
        "**[SPEAKER_00]**: 本地部署的"
    )


def test_segment_level_speaker_remains_a_safe_fallback_without_words():
    assert (
        _segments_to_markdown(
            [
                {"speaker": "A", "text": "第一句"},
                {"speaker": "A", "text": "第二句"},
                {"speaker": "B", "text": "回答"},
            ]
        )
        == "**[A]**: 第一句 第二句\n\n**[B]**: 回答"
    )


def test_word_timestamp_transcription_uses_the_already_loaded_model(monkeypatch):
    class FakeModel:
        def transcribe(self, audio, **kwargs):
            assert audio == "audio"
            assert kwargs == {
                "language": "zh",
                "beam_size": 5,
                "vad_filter": True,
                "word_timestamps": True,
            }
            return (
                iter(
                    [
                        SimpleNamespace(
                            start=1.0,
                            end=2.0,
                            text="问题回答",
                            words=[
                                SimpleNamespace(
                                    word="问题",
                                    start=1.0,
                                    end=1.4,
                                    probability=0.9,
                                ),
                                SimpleNamespace(
                                    word="回答",
                                    start=1.5,
                                    end=2.0,
                                    probability=0.8,
                                ),
                            ],
                        )
                    ]
                ),
                SimpleNamespace(language="zh"),
            )

    monkeypatch.setattr(
        whisperx_engine,
        "whisper_model",
        SimpleNamespace(model=FakeModel()),
    )

    result = whisperx_engine._transcribe_with_word_timestamps(
        "audio",
        language="zh",
    )

    assert result["language"] == "zh"
    assert result["segments"][0]["words"] == [
        {"word": "问题", "start": 1.0, "end": 1.4, "score": 0.9},
        {"word": "回答", "start": 1.5, "end": 2.0, "score": 0.8},
    ]
