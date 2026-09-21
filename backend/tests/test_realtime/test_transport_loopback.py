"""Native ICE/DTLS/SRTP/SCTP exercise; the dedicated CI gate requires aiortc.

Only detectors and business/model callbacks are replaced. No model downloads,
external STUN/TURN, microphone hardware or cloud LLM is used.
"""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid
import pytest

try:
    from aiortc import (
        AudioStreamTrack,
        RTCConfiguration,
        RTCPeerConnection,
        RTCSessionDescription,
    )
except ImportError:
    if os.getenv("REQUIRE_WEBRTC") == "1":
        raise
    pytestmark = pytest.mark.skip(
        reason="native WebRTC requires optional aiortc; dedicated CI installs it"
    )

from app.media.realtime import transport
from app.media.realtime.config import RealtimeConfig
from app.schemas.realtime import MediaOffer


async def test_real_local_audio_and_control_roundtrip_then_cleanup(monkeypatch):
    detector = SimpleNamespace(
        speech=Mock(return_value=0.0), ended=Mock(return_value=0.0)
    )
    monkeypatch.setattr(transport, "Detectors", lambda _: detector)
    services = SimpleNamespace(
        state=AsyncMock(return_value={"question_message_id": 1, "messages": []}),
        authorize=AsyncMock(),
        release=Mock(),
    )
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    peer.addTransceiver(AudioStreamTrack(), direction="sendonly")
    channel = peer.createDataChannel("copilot-media-v1", ordered=True)
    received = asyncio.Queue()

    @channel.on("message")
    def incoming(data):
        received.put_nowait(json.loads(data))

    registry = transport.Registry()
    key = (1, "r", str(uuid.uuid4()))
    try:
        async with asyncio.timeout(15):
            await peer.setLocalDescription(await peer.createOffer())
            offer = MediaOffer(client_session_id=key[2], sdp=peer.localDescription.sdp)
            answer = await registry.connect(
                key=key,
                config=RealtimeConfig(),
                offer=offer,
                services_factory=lambda _: services,
            )
            # A lost signalling response reuses the exact answer, not a new connection.
            duplicate = await registry.connect(
                key=key,
                config=RealtimeConfig(),
                offer=offer,
                services_factory=lambda _: pytest.fail("duplicate allocation"),
            )
            assert duplicate == answer
            await peer.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type="answer")
            )
            state = await received.get()
            assert state["type"] == "state" and state["question_message_id"] == 1
            channel.send(
                json.dumps({"connection_id": answer["connection_id"], "action": "ping"})
            )
            for _ in range(100):
                if detector.speech.call_count:
                    break
                await asyncio.sleep(0.02)
            assert detector.speech.call_count > 0
            await registry.disconnect(key, answer["connection_id"])
            assert not registry.connections
            services.release.assert_called_once()
    finally:
        await registry.close()
        await peer.close()
