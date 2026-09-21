"""Finite local decoding with backpressure and owned process-group cleanup.

Only bounded PCM blocks leave this decoder. It does not run an ASR model, keep
an entire recording in RAM, or accept network URLs. Use as an async context
manager so early consumer exit cannot orphan FFmpeg.
"""

from __future__ import annotations

import asyncio
import math
import os
from pathlib import Path
import stat

from app.core.isolated_process import finish_cleanup, stop_process_group
from app.local_inference.audio import MAX_PCM_BYTES, SAMPLE_RATE


class PCMStream:
    def __init__(
        self, path: str, *, max_bytes: int, max_ms: int, read_timeout: float = 30
    ):
        self.path = Path(path)
        self.max_bytes, self.max_ms, self.read_timeout = max_bytes, max_ms, read_timeout
        if (
            type(max_bytes) is not int
            or max_bytes <= 0
            or type(max_ms) is not int
            or max_ms <= 0
            or type(read_timeout) not in (int, float)
            or not math.isfinite(read_timeout)
            or not 0 < read_timeout <= 600
        ):
            raise ValueError("invalid_decoder_limits")
        self.process = self.creation = None
        self.fd = None
        self.identity = None
        self.consumed = 0
        self.complete = False

    async def __aenter__(self):
        if os.name != "posix":
            raise RuntimeError("audio_decoder_requires_linux_or_wsl2")
        try:
            self.fd = os.open(
                self.path.absolute(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            )
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= self.max_bytes:
                raise ValueError("audio_input_size_invalid")
            self.identity = (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            # Pin the opened file, not a mutable pathname or a URL. This endpoint
            # is called only after the application's file ownership checks.
            self.creation = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    "wav,mp3,flac,ogg,matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,aac",
                    "-i",
                    f"/proc/self/fd/{self.fd}",
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-ar",
                    str(SAMPLE_RATE),
                    "-ac",
                    "1",
                    "-f",
                    "s16le",
                    "pipe:1",
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    pass_fds=(self.fd,),
                    env={
                        k: os.environ[k]
                        for k in ("PATH", "LD_LIBRARY_PATH")
                        if k in os.environ
                    },
                    start_new_session=True,
                    limit=65536,
                )
            )
            self.process = await asyncio.shield(self.creation)
            return self
        except BaseException:
            await finish_cleanup(asyncio.create_task(self._close()))
            raise

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.complete:
            raise StopAsyncIteration
        async with asyncio.timeout(self.read_timeout):
            try:
                pcm = await self.process.stdout.readexactly(MAX_PCM_BYTES)
            except asyncio.IncompleteReadError as exc:
                pcm = exc.partial
                code = await self.process.wait()
                if code or len(pcm) % 2:
                    raise ValueError("audio_decode_incomplete") from None
                self.complete = True
        self.consumed += len(pcm)
        info = os.fstat(self.fd)
        if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != self.identity:
            raise ValueError("audio_source_changed")
        if self.consumed * 1000 > self.max_ms * SAMPLE_RATE * 2:
            raise ValueError("audio_duration_exceeds_limit")
        if not pcm:
            if not self.consumed:
                raise ValueError("audio_has_no_samples")
            raise StopAsyncIteration
        return pcm

    async def __aexit__(self, *exc):
        await finish_cleanup(asyncio.create_task(self._close()))
        return False

    async def _close(self):
        try:
            if self.process is None and self.creation is not None:
                try:
                    self.process = await finish_cleanup(self.creation)
                except OSError:
                    pass
            if self.process is not None:

                async def discard():
                    while await self.process.stdout.read(65536):
                        pass

                drain = asyncio.create_task(discard())
                try:
                    await stop_process_group(self.process, 1)
                finally:
                    drain.cancel()
                    await asyncio.gather(drain, return_exceptions=True)
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
