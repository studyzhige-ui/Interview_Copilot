import asyncio
import os
import importlib.util
import json
import math
import struct
from fractions import Fraction
from types import SimpleNamespace
from uuid import uuid4
import pytest

from app.media.realtime.transport import Peer, validate_offer
from tests.test_realtime.test_session import Application, until


def test_signalling_rejects_unapproved_targets_video_and_ambiguous_candidates():
    allowed = "127.0.0.0/8,::1/128"
    prefix = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 96\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n"
    good = prefix + "a=candidate:1 1 udp 123 127.0.0.1 4321 typ host\r\n"
    validate_offer(good, allowed)
    for value in (
        good.replace("127.0.0.1", "8.8.8.8"),
        good.replace("127.0.0.1", "host.local"),
        good.replace("udp 123", "tcp 123"),
        good.replace("typ host", "typ relay"),
        good + "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
        good.replace("4321", "0"),
    ):
        with pytest.raises(ValueError):
            validate_offer(value, allowed)


async def test_real_dtls_rtp_datachannel_draft_commit_audio_and_cleanup():
    # This dependency is required in the realtime CI job; never replace with mocks.
    if os.getenv("REQUIRE_REALTIME") == "1":
        assert importlib.util.find_spec("aiortc"), "Required WebRTC dependency missing"
    aiortc = pytest.importorskip("aiortc")
    from av import AudioFrame

    class Audio(aiortc.MediaStreamTrack):
        kind = "audio"

        def __init__(self):
            super().__init__()
            self.position = 0

        async def recv(self):
            await asyncio.sleep(0.02)
            frame = AudioFrame(format="s16", layout="mono", samples=960)
            # Speech starts after the initial media channel handshake.
            value = 6000 if 24000 <= self.position < 48000 else 0
            frame.planes[0].update(
                b"".join(
                    struct.pack(
                        "<h",
                        int(
                            value
                            * math.sin(2 * math.pi * 220 * (self.position + i) / 48000)
                        ),
                    )
                    for i in range(960)
                )
            )
            frame.pts = self.position
            frame.sample_rate = 48000
            frame.time_base = Fraction(1, 48000)
            self.position += 960
            return frame

    app = Application()
    events = []
    client = aiortc.RTCPeerConnection(aiortc.RTCConfiguration(iceServers=[]))
    channel = client.createDataChannel("interview-media-v1", ordered=True)
    client.addTrack(Audio())

    @channel.on("message")
    def message(raw):
        event = json.loads(raw)
        events.append(event)
        if event["type"] == "audio_end":
            start = next(e for e in reversed(events) if e["type"] == "audio_start")
            channel.send(
                json.dumps(
                    {
                        "type": "playback",
                        "audio_id": start["audio_id"],
                        "played_samples": start["samples"],
                        "complete": True,
                    }
                )
            )

    server = Peer(
        SimpleNamespace(id=str(uuid4()), generation=1),
        app,
        auto_submit=False,
        threshold=0.015,
        silence_ms=300,
    )
    try:
        await client.setLocalDescription(await client.createOffer())
        validate_offer(
            client.localDescription.sdp,
            "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128",
        )
        answer = await server.negotiate(client.localDescription.sdp)
        await client.setRemoteDescription(
            aiortc.RTCSessionDescription(type="answer", sdp=answer)
        )
        await until(lambda: any(e["type"] == "final" for e in events), 12)
        assert not app.submissions
        draft = next(e for e in events if e["type"] == "final")
        request_id = str(uuid4())
        channel.send(
            json.dumps(
                {
                    "type": "commit",
                    "draft_id": draft["draft_id"],
                    "request_id": request_id,
                }
            )
        )
        await until(lambda: any(e["type"] == "speech_done" for e in events), 8)
        assert app.submissions == [(1, draft["text"], request_id)]
        assert app.acks and app.acks[-1][-1] is True
        assert any(e["type"] == "audio" for e in events)
        assert all(e["generation"] == 1 for e in events)
        assert [e["seq"] for e in events] == sorted({e["seq"] for e in events})
    finally:
        await server.close()
        await client.close()
    assert app.closed == 1
    assert server.pc.connectionState == "closed"
    assert not server.tasks and not server.session.tasks
