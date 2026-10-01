"""Local-network WebRTC ingress and ordered control/PCM egress, no cloud relay.

All model work is outside transport callbacks; queues, frames, lifetime and SDP
are bounded. A replaced connection cannot commit through the application lease.
"""

from __future__ import annotations
import asyncio
import hashlib
import ipaddress
import json
import re
import time
import uuid

from app.local_inference.protocol import loads
from app.schemas.realtime import MediaControl
from .session import MediaSession
from .detection import Detectors


def validate_sdp(sdp, allowed_cidrs):
    if not isinstance(sdp, str) or not 0 < len(sdp.encode()) <= 65536 or "\0" in sdp:
        raise ValueError("invalid_media_sdp")
    networks = [
        ipaddress.ip_network(item.strip())
        for item in allowed_cidrs.split(",")
        if item.strip()
    ]
    media = []
    candidates = 0
    for line in sdp.splitlines():
        if len(line) > 4096:
            raise ValueError("invalid_media_sdp")
        if line.startswith("m="):
            media.append(line.split()[0][2:])
        if not line.startswith("a=candidate:"):
            continue
        candidates += 1
        parts = line.split()
        if (
            candidates > 32
            or len(parts) < 8
            or parts[2].lower() != "udp"
            or parts[6:8] != ["typ", "host"]
            or not parts[5].isdigit()
            or not 1024 <= int(parts[5]) <= 65535
        ):
            raise ValueError("unsupported_media_candidate")
        address = parts[4]
        # Browsers mask host candidates with an mDNS UUID; never resolve a
        # client-supplied public DNS name or accept relay/metadata addresses.
        if re.fullmatch(r"[a-fA-F0-9-]{36}\.local", address):
            continue
        ip = ipaddress.ip_address(address)
        if (
            ip.is_multicast
            or ip.is_unspecified
            or ip.is_link_local
            or not any(ip in network for network in networks)
        ):
            raise ValueError("media_candidate_outside_local_network")
    if sorted(media) != ["application", "audio"] or not candidates:
        raise ValueError("media_requires_one_audio_and_control_channel")


class Connection:
    def __init__(self, *, config, services, connection_id):
        from aiortc import RTCConfiguration, RTCPeerConnection

        self.config, self.services, self.id = config, services, connection_id
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.channel = self.session = None
        self.queue = asyncio.Queue(maxsize=32)
        self.controls = asyncio.Queue(maxsize=16)
        self.tasks = set()
        self.closed = False
        self.offer_hash = self.answer = None
        self.tracks = 0
        self.last_command = 0.0
        self.started = False
        self.send_lock = asyncio.Lock()

    def task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)

        def done(finished):
            self.tasks.discard(finished)
            if (
                not finished.cancelled()
                and finished.exception() is not None
                and not self.closed
            ):
                self.task(self.close())

        task.add_done_callback(done)
        return task

    async def negotiate(self, offer):
        from aiortc import RTCSessionDescription
        from app.media.application.workers import pool

        detectors = await pool("probe").run(Detectors, self.config)
        self.session = MediaSession(
            config=self.config,
            services=self.services,
            detectors=detectors,
            send=self.send,
            connection_id=self.id,
        )

        @self.pc.on("datachannel")
        def channel_open(channel):
            if (
                self.channel is not None
                or channel.label != "copilot-media-v1"
                or not channel.ordered
                or channel.maxRetransmits is not None
                or channel.maxPacketLifeTime is not None
            ):
                self.task(self.close())
                return
            self.channel = channel

            @channel.on("message")
            def message(data):
                if (
                    not isinstance(data, str)
                    or len(data.encode()) > 4096
                    or self.controls.full()
                ):
                    self.task(self.close())
                    return
                self.controls.put_nowait(data)

            @channel.on("close")
            def closed():
                self.task(self.close())

            self.task(self.control_loop())
            self.task(self.session.open())

        @self.pc.on("track")
        def track_open(track):
            self.tracks += 1
            if track.kind != "audio" or self.tracks != 1:
                track.stop()
                self.task(self.close())
            else:
                self.task(self.read_audio(track))

        @self.pc.on("connectionstatechange")
        async def connection_changed():
            if self.pc.connectionState in {"failed", "closed"}:
                await self.close()

        self.task(self.consume_audio())
        self.task(self.deadline())
        await self.pc.setRemoteDescription(
            RTCSessionDescription(sdp=offer.sdp, type="offer")
        )
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        self.offer_hash = hashlib.sha256(offer.sdp.encode()).hexdigest()
        self.answer = {
            "connection_id": self.id,
            "client_session_id": str(offer.client_session_id),
            "type": "answer",
            "sdp": self.pc.localDescription.sdp,
        }
        return self.answer

    async def deadline(self):
        for _ in range(self.config.session_seconds):
            await asyncio.sleep(1)
            if self.session and self.session.closed:
                break
            if not self.started and _ >= 20:
                break
        await self.close()

    async def send(self, message):
        async with self.send_lock:
            async with asyncio.timeout(5):
                while (
                    self.channel is not None
                    and self.channel.readyState == "open"
                    and self.channel.bufferedAmount > 128_000
                ):
                    await asyncio.sleep(0.01)
                if (
                    self.closed
                    or self.channel is None
                    or self.channel.readyState != "open"
                ):
                    raise ConnectionError("media_control_not_open")
                encoded = json.dumps(message, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode()) > 64000:
                    raise ValueError("media_event_capacity")
                self.channel.send(encoded)

    async def control_loop(self):
        while not self.closed:
            raw = await self.controls.get()
            command = MediaControl.model_validate(loads(raw.encode()))
            if command.action not in {"ping", "ack"}:
                now = time.monotonic()
                if now - self.last_command < 0.1:
                    raise ValueError("media_command_rate")
                self.last_command = now
            await self.session.control(command)

    async def read_audio(self, track):
        from av import AudioResampler

        resampler = AudioResampler(format="s16", layout="mono", rate=16000)
        buffer = bytearray()
        while not self.closed:
            frame = await asyncio.wait_for(track.recv(), 15)
            self.started = True
            if frame.samples > 96000 or frame.sample_rate not in (
                8000,
                16000,
                24000,
                32000,
                44100,
                48000,
            ):
                raise ValueError("media_frame_capacity")
            for mono in resampler.resample(frame):
                buffer.extend(mono.to_ndarray().astype("<i2", copy=False).tobytes())
            if len(buffer) > 192000:
                raise ValueError("media_resample_capacity")
            while len(buffer) >= 1024:
                if self.queue.full():
                    raise ValueError("media_ingress_backpressure")
                self.queue.put_nowait(bytes(buffer[:1024]))
                del buffer[:1024]

    async def consume_audio(self):
        while not self.closed:
            pcm = await self.queue.get()
            if self.channel is not None and self.channel.readyState == "open":
                await self.session.feed(pcm)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.session:
            await self.session.close()
        current = asyncio.current_task()
        tasks = [task for task in self.tasks if task is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.pc.close()
        self.services.release()


class Registry:
    def __init__(self):
        self.connections = {}
        self.lock = asyncio.Lock()

    async def connect(self, *, key, config, offer, services_factory):
        validate_sdp(offer.sdp, config.allowed_cidrs)
        async with self.lock:
            for identity, connection in list(self.connections.items()):
                if connection.closed:
                    self.connections.pop(identity)
            previous = self.connections.get(key)
            if (
                previous
                and previous.offer_hash
                == hashlib.sha256(offer.sdp.encode()).hexdigest()
            ):
                return previous.answer
            if previous:
                await previous.close()
                self.connections.pop(key)
            if len(self.connections) >= config.max_sessions:
                raise ValueError("media_session_capacity")
            connection_id = str(uuid.uuid4())
            services = services_factory(connection_id)
            connection = None
            try:
                connection = Connection(
                    config=config, services=services, connection_id=connection_id
                )
                async with asyncio.timeout(20):
                    result = await connection.negotiate(offer)
                self.connections[key] = connection
                return result
            except BaseException:
                if connection:
                    await asyncio.shield(connection.close())
                else:
                    services.release()
                raise

    async def disconnect(self, key, connection_id):
        connection = self.connections.get(key)
        if connection and connection.id == connection_id:
            await connection.close()
            self.connections.pop(key, None)

    async def close(self):
        await asyncio.gather(
            *(item.close() for item in self.connections.values()),
            return_exceptions=True,
        )
        self.connections.clear()


registry = Registry()
