"""Authenticated, local-network WebRTC transport with no public ICE services.

RTP carries microphone audio. A reliable ordered data channel carries control and
bounded synthesized PCM chunks, allowing explicit browser playback accounting.
Media tasks and peer connections have one owner and finite lifetimes.
"""

from __future__ import annotations
import asyncio
import ipaddress
import json
import time

from app.media.realtime.session import RealtimeSession
from app.media.realtime.vad import FRAME_BYTES
from app.schemas.realtime import MediaEvent

PROTOCOL = "interview-media-v1"
PEERS: dict[str, "Peer"] = {}
MAX_PEERS = 16
_creating = 0


def validate_offer(sdp: str, cidrs: str):
    if not isinstance(sdp, str) or not 1 <= len(sdp.encode()) <= 65536:
        raise ValueError("invalid_media_sdp")
    networks = [
        ipaddress.ip_network(value.strip())
        for value in cidrs.split(",")
        if value.strip()
    ]
    if not 1 <= len(networks) <= 16:
        raise ValueError("invalid_media_network_policy")
    lines = sdp.splitlines()
    if len(lines) > 512 or any("\x00" in line for line in lines):
        raise ValueError("invalid_media_sdp")
    kinds = [line.split()[0] for line in lines if line.startswith("m=")]
    if sorted(kinds) != ["m=application", "m=audio"]:
        raise ValueError("media_requires_one_audio_and_control_channel")
    candidates = [
        line[len("a=candidate:") :] for line in lines if line.startswith("a=candidate:")
    ]
    if not 1 <= len(candidates) <= 32:
        raise ValueError("invalid_media_candidates")
    for candidate in candidates:
        fields = candidate.split()
        if (
            len(fields) < 8
            or fields[1] != "1"
            or fields[2].lower() != "udp"
            or fields[6:8] != ["typ", "host"]
        ):
            raise ValueError("media_requires_host_udp_candidates")
        try:
            address = ipaddress.ip_address(fields[4])
            port = int(fields[5])
        except ValueError:
            raise ValueError("media_requires_explicit_local_ip") from None
        if (
            not 1 <= port <= 65535
            or address.is_multicast
            or address.is_unspecified
            or not any(address in network for network in networks)
        ):
            raise ValueError("media_candidate_outside_allowed_network")
    if any(line.startswith(("a=remote-candidates:", "a=ice-lite")) for line in lines):
        raise ValueError("invalid_media_ice_mode")


class Peer:
    def __init__(self, lease, app, *, auto_submit, threshold, silence_ms):
        # Optional native media dependencies are loaded only on explicit enablement.
        from aiortc import RTCPeerConnection, RTCConfiguration

        self.lease = lease
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.channel = None
        self.closed = self.started = False
        self.track_count = 0
        self.sequence = 0
        self.send_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()
        self.controls: asyncio.Queue = asyncio.Queue(maxsize=16)
        self.session = RealtimeSession(
            app,
            self.emit,
            auto_submit=auto_submit,
            threshold=threshold,
            silence_ms=silence_ms,
        )
        self.pc.on("datachannel", self.on_channel)
        self.pc.on("track", self.on_track)
        self.pc.on("connectionstatechange", self.on_connection)
        self.spawn(self.watch())

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)

        def done(finished):
            self.tasks.discard(finished)
            if not finished.cancelled():
                finished.exception()

        task.add_done_callback(done)
        return task

    async def negotiate(self, sdp):
        from aiortc import RTCSessionDescription

        try:
            async with asyncio.timeout(20):
                await self.pc.setRemoteDescription(
                    RTCSessionDescription(sdp=sdp, type="offer")
                )
                await self.pc.setLocalDescription(await self.pc.createAnswer())
            return self.pc.localDescription.sdp
        except BaseException:
            await self.close()
            raise

    async def emit(self, event):
        # Serialize backpressure and sequence assignment, including control events
        # racing with speech output. A single ordered channel must stay ordered.
        async with self.send_lock:
            if self.closed or self.channel is None or self.channel.readyState != "open":
                return
            self.sequence += 1
            raw = json.dumps(
                MediaEvent.model_validate(
                    {
                        "v": 1,
                        "generation": self.lease.generation,
                        "seq": self.sequence,
                        **event,
                    }
                ).model_dump(exclude_unset=True),
                ensure_ascii=False,
                allow_nan=False,
            )
            if len(raw.encode()) > 65536:
                raise ValueError("media_event_capacity")
            async with asyncio.timeout(5):
                while self.channel.bufferedAmount > 262144:
                    await asyncio.sleep(0.01)
                    if self.closed or self.channel.readyState != "open":
                        raise ConnectionError("media_channel_closed")
                self.channel.send(raw)

    def on_channel(self, channel):
        if (
            self.channel is not None
            or channel.label != PROTOCOL
            or not channel.ordered
            or channel.maxRetransmits is not None
            or channel.maxPacketLifeTime is not None
        ):
            self.spawn(self.close())
            return
        self.channel = channel
        channel.on("open", lambda: self.spawn(self.begin()))
        channel.on("close", lambda: self.spawn(self.close()))

        def receive(raw):
            if not isinstance(raw, str) or len(raw.encode()) > 2048:
                self.spawn(self.close())
                return
            try:
                self.controls.put_nowait(raw)
            except asyncio.QueueFull:
                self.spawn(self.close())

        channel.on("message", receive)
        if channel.readyState == "open":
            self.spawn(self.begin())

    async def begin(self):
        if self.started or self.closed:
            return
        self.started = True
        try:
            await self.session.start()
            self.spawn(self.consume_controls())
        except Exception:
            await self.close()

    def on_track(self, track):
        self.track_count += 1
        if track.kind != "audio" or self.track_count != 1:
            track.stop()
            self.spawn(self.close())
            return
        self.spawn(self.receive_audio(track))

    async def receive_audio(self, track):
        from av import AudioResampler

        resampler = AudioResampler(format="s16", layout="mono", rate=16000)
        pending = bytearray()
        started, samples = time.monotonic(), 0
        try:
            while not self.closed:
                frame = await asyncio.wait_for(track.recv(), 15)
                if not 0 < frame.samples <= 48000 or frame.sample_rate not in (
                    8000,
                    16000,
                    24000,
                    32000,
                    44100,
                    48000,
                ):
                    raise ValueError("invalid_media_frame")
                for converted in resampler.resample(frame):
                    pcm = converted.to_ndarray().astype("<i2", copy=False).tobytes()
                    samples += len(pcm) // 2
                    if samples > (time.monotonic() - started + 3) * 16000:
                        raise ValueError("media_input_rate_exceeded")
                    pending.extend(pcm)
                    while len(pending) >= FRAME_BYTES:
                        block = bytes(pending[:FRAME_BYTES])
                        del pending[:FRAME_BYTES]
                        if self.started:
                            await self.session.feed(block)
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await self.emit({"type": "error", "code": "media_input_failed"})
            finally:
                await self.close()
        finally:
            track.stop()

    async def consume_controls(self):
        try:
            while not self.closed:
                raw = await self.controls.get()
                try:
                    await self.session.control(raw)
                finally:
                    self.controls.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await self.emit({"type": "error", "code": "invalid_media_control"})
            finally:
                await self.close()

    async def on_connection(self):
        if self.pc.connectionState in ("closed", "failed"):
            await self.close()

    async def watch(self):
        started = time.monotonic()
        while not self.closed:
            await asyncio.sleep(1)
            if self.session.closed or (
                not self.started and time.monotonic() - started > 25
            ):
                await self.close()

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if PEERS.get(self.lease.id) is self:
            PEERS.pop(self.lease.id, None)
        tasks = [t for t in self.tasks if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        try:
            await self.session.close()
        finally:
            await self.pc.close()
            await asyncio.gather(*tasks, return_exceptions=True)


def reserve():
    global _creating
    if len(PEERS) + _creating >= MAX_PEERS:
        raise ValueError("media_process_capacity")
    _creating += 1


def unreserve():
    global _creating
    _creating -= 1


async def close_all():
    await asyncio.gather(
        *(peer.close() for peer in list(PEERS.values())), return_exceptions=True
    )
