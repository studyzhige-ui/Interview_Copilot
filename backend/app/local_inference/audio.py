"""Bounded PCM transport and normalization shared by media adapters."""

from __future__ import annotations

import base64
import binascii
import hashlib
import unicodedata

from .errors import ProtocolError

SAMPLE_RATE = 16000
MAX_SECONDS = 30
MAX_PCM_BYTES = SAMPLE_RATE * MAX_SECONDS * 2


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


def _lexical(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", text)
        if not c.isspace() and not unicodedata.category(c).startswith("P")
    )
