import uuid
import pytest
from pydantic import ValidationError
from app.media.realtime.detection import SpeechGate, probability
from app.media.realtime.playback import sentences, pcm_from_wav
from app.media.realtime.transport import validate_sdp, Registry
from app.media.realtime.config import RealtimeConfig
from app.schemas.realtime import MediaControl, MediaOffer


def offer(address="192.168.1.20", kind="host", port=12345):
    return f"v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=candidate:1 1 udp 1 {address} {port} typ {kind}\r\n"


def test_network_boundary_is_explicit_local_host_ice():
    config = RealtimeConfig()
    for address in ("192.168.1.20", "127.0.0.1", "::1", f"{uuid.uuid4()}.local"):
        validate_sdp(offer(address), config.allowed_cidrs)
    for sdp in (
        offer("169.254.169.254"),
        offer("8.8.8.8"),
        offer("example.com"),
        offer(kind="relay"),
        offer(port=53),
        offer() + "m=video 9 RTP/AVP 100\n",
        "x" * 65537,
    ):
        with pytest.raises(ValueError):
            validate_sdp(sdp, config.allowed_cidrs)


def test_controls_reject_coercion_extras_and_ambiguous_actions():
    for fields in (
        {"action": "ack", "samples": True, "playback_id": "0" * 36},
        {"action": "commit"},
        {"action": "ping", "request_id": "0" * 36},
        {"action": "ack", "samples": 1},
        {"action": "ping", "url": "file://x"},
    ):
        with pytest.raises(ValidationError):
            MediaControl(connection_id="0" * 36, **fields)


def test_gate_needs_speech_and_never_claims_silence_is_semantic_end():
    gate = SpeechGate(0.5, 800)
    block = b"\0\0" * 512
    for _ in range(40):
        assert gate.feed(block, 0.0) == (False, b"")
    for _ in range(5):
        assert not gate.feed(block, 1.0)[0]
    started, prefix = gate.feed(block, 1.0)
    assert started and len(prefix) <= 8192
    for _ in range(24):
        gate.feed(block, 0.0)
    assert not gate.may_end
    gate.feed(block, 0.0)
    assert gate.may_end
    old = gate.version
    gate.feed(block, 1.0)
    assert gate.version > old and not gate.may_end
    for value in (float("nan"), float("inf"), -1, 2):
        with pytest.raises(ValueError):
            probability(value)


def test_sentence_buffering_preserves_all_nonempty_text_and_budgets():
    text = "你好！First. " + "z" * 1000
    parts = list(sentences(text))
    assert all(len(part) <= 240 for part in parts)
    assert "".join(parts) == text
    with pytest.raises(ValueError):
        list(sentences("x" * 16001))
    with pytest.raises(Exception):
        pcm_from_wav(b"not audio")


async def test_invalid_offer_never_allocates_or_claims_business_lease():
    registry = Registry()
    with pytest.raises(ValueError):
        await registry.connect(
            key=(1, "r", "c"),
            config=RealtimeConfig(),
            offer=MediaOffer(client_session_id=uuid.uuid4(), sdp=offer("8.8.8.8")),
            services_factory=lambda _: pytest.fail("claimed before validating"),
        )
    assert not registry.connections
