"""Shared finite PCM envelope validation; no model execution."""

import pytest

from app.local_inference.audio import pcm_payload, decode_pcm, MAX_PCM_BYTES
from app.local_inference.protocol import ProtocolError


@pytest.mark.parametrize(
    "pcm",
    [b"", b"x", b"x" * (MAX_PCM_BYTES + 2), "text"],
    ids=["empty", "unaligned", "oversized", "wrong-type"],
)
def test_invalid_pcm(pcm):
    with pytest.raises(ProtocolError):
        pcm_payload(pcm)


def test_pcm_roundtrip_and_hash_binding():
    pcm = b"\0\0\xff\x7f\0\x80"
    envelope = pcm_payload(pcm)
    assert decode_pcm(envelope) == pcm
    with pytest.raises(ProtocolError):
        decode_pcm({**envelope, "sha256": "a" * 64})


@pytest.mark.parametrize(
    "key,value",
    [
        ("sample_rate", True),
        ("sample_rate", 44100),
        ("samples", -1),
        ("samples", True),
        ("data", "https://audio"),
        ("data", "€"),
        ("data", "AA=="),
        ("encoding", "wav"),
    ],
)
def test_bad_audio_envelope(key, value):
    with pytest.raises(ProtocolError):
        decode_pcm({**pcm_payload(b"\0\0"), key: value})
