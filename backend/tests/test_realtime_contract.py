"""Current media admission and playback acknowledgment boundaries."""

import pytest
from app.media.realtime.transport import validate_sdp
from app.media.realtime.playback import Playback, sentences


def offer(address="127.0.0.1", kind="host"):
    return f"m=audio 9 UDP/TLS/RTP/SAVPF 111\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\na=candidate:1 1 udp 1 {address} 5000 typ {kind}\n"


def test_only_local_audio_and_ordered_control_are_admitted():
    validate_sdp(offer(), "127.0.0.0/8")
    for sdp in (
        offer("169.254.169.254"),
        offer("8.8.8.8"),
        offer(kind="relay"),
        offer() + "m=video 9 RTP 96\n",
    ):
        with pytest.raises(ValueError):
            validate_sdp(sdp, "127.0.0.0/8")


def test_playback_cannot_acknowledge_undelivered_or_rewind():
    playback = Playback("playback", 1, generated=24000, delivered=12000)
    playback.acknowledge(6000)
    for value in (5999, 12001, True):
        with pytest.raises(ValueError):
            playback.acknowledge(value)
    assert playback.snapshot("interrupted")["client_reported_samples"] == 6000
    text = "第一句。" + "长句" * 300 + "！最后一句。"
    pieces = list(sentences(text))
    assert "".join(pieces) == text and max(map(len, pieces)) <= 240
