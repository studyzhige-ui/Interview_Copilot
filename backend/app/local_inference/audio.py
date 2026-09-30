"""Bounded PCM and typed ASR/alignment contracts; never paths or URLs on IPC.

This is finite-clip inference, not a stateful streaming-ASR protocol. Audio
positions are sample based. A transcription has no implied timestamps, speaker
identity, or certainty. Alignment does not certify transcript correctness.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import unicodedata

from .errors import ProtocolError

AUDIO_OUTPUT_TOKENS = 4096
SAMPLE_RATE = 16000
MAX_SECONDS = 30
MAX_PCM_BYTES = SAMPLE_RATE * MAX_SECONDS * 2
MAX_AUDIO_TEXT = 16000
AUDIO_ROLES = frozenset({"transcription", "alignment"})
ASR_CONTRACT = "qwen-asr-transformers-pcm16-v1"
ALIGN_CONTRACT = "qwen-forced-aligner-pcm16-v1"


def _fail(code):
    raise ProtocolError(code)


def pcm_payload(pcm: bytes) -> dict:
    if not isinstance(pcm, bytes) or not 0 < len(pcm) <= MAX_PCM_BYTES or len(pcm) % 2:
        _fail("invalid_pcm_size")
    return {
        "encoding": "pcm_s16le",
        "sample_rate": SAMPLE_RATE,
        "samples": len(pcm) // 2,
        "sha256": hashlib.sha256(pcm).hexdigest(),
        "data": base64.b64encode(pcm).decode("ascii"),
    }


def decode_pcm(value) -> bytes:
    if not isinstance(value, dict) or set(value) != {
        "encoding",
        "sample_rate",
        "samples",
        "sha256",
        "data",
    }:
        _fail("invalid_audio_envelope")
    if (
        value["encoding"] != "pcm_s16le"
        or type(value["sample_rate"]) is not int
        or value["sample_rate"] != SAMPLE_RATE
        or type(value["samples"]) is not int
        or not 0 < value["samples"] <= SAMPLE_RATE * MAX_SECONDS
    ):
        _fail("invalid_audio_format")
    encoded = value["data"]
    if not isinstance(encoded, str) or len(encoded) > (MAX_PCM_BYTES + 2) // 3 * 4:
        _fail("invalid_pcm_size")
    try:
        pcm = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        _fail("invalid_audio_base64")
    if (
        len(pcm) != value["samples"] * 2
        or hashlib.sha256(pcm).hexdigest() != value["sha256"]
    ):
        _fail("audio_identity_mismatch")
    return pcm


def validate_audio_request(task):
    decode_pcm(task["audio"])
    text, language = task["text"], task["language"]
    if (
        not isinstance(text, str)
        or len(text.encode()) > MAX_AUDIO_TEXT
        or not isinstance(language, (str, type(None)))
        or (isinstance(language, str) and (not language.strip() or len(language) > 80))
    ):
        _fail("invalid_audio_text_or_language")
    if task["role"] == "transcription":
        if task["operation"] != "transcribe" or text:
            _fail("invalid_audio_operation")
    elif task["operation"] != "align" or not text.strip() or language is None:
        _fail("invalid_audio_operation")
    return task


def _lexical(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", text)
        if not c.isspace() and not unicodedata.category(c).startswith("P")
    )


def validate_audio_result(task, value):
    if not isinstance(value, dict) or set(value) != {"text", "language", "words"}:
        _fail("invalid_audio_result")
    text, language, words = value["text"], value["language"], value["words"]
    if (
        not isinstance(text, str)
        or len(text.encode()) > MAX_AUDIO_TEXT
        or not isinstance(language, str)
        or len(language) > 80
        or not isinstance(words, list)
        or len(words) > 8000
    ):
        _fail("invalid_audio_result")
    if task["role"] == "transcription":
        if words:
            _fail("asr_must_not_invent_alignment")
        return value
    if text != task["text"] or language != task["language"]:
        _fail("alignment_input_mismatch")
    limit = task["audio"]["samples"] / SAMPLE_RATE
    previous = 0.0
    for word in words:
        if (
            not isinstance(word, dict)
            or set(word) != {"text", "start", "end"}
            or not isinstance(word["text"], str)
            or not word["text"]
        ):
            _fail("invalid_alignment_word")
        start, end = word["start"], word["end"]
        if start is None and end is None:
            continue
        if (
            type(start) not in (int, float)
            or type(end) not in (int, float)
            or not math.isfinite(start)
            or not math.isfinite(end)
            or not 0 <= start < end <= limit
            or start < previous
        ):
            _fail("invalid_alignment_time")
        previous = start
    if _lexical("".join(w["text"] for w in words)) != _lexical(text):
        _fail("alignment_text_coverage_mismatch")
    return value
