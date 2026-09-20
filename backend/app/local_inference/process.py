"""Resident model subprocess lifecycle; a cancelled waiter still owns cleanup."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import os
from pathlib import Path
import tempfile

from app.core.isolated_process import finish_cleanup, stop_process_group
from .protocol import ProtocolError, receive, send, validate_output

CHILD = Path(__file__).with_name("child.py")


class WorkerFailure(RuntimeError):
    pass


def environment(work: Path) -> dict[str, str]:
    allowed = ("PATH", "LD_LIBRARY_PATH", "CUDA_VISIBLE_DEVICES")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(
        COPILOT_BROKER_PID=str(os.getpid()),
        HOME=str(work),
        TMPDIR=str(work),
        XDG_CACHE_HOME=str(work / "cache"),
        HF_HOME=str(work / "hf"),
        HF_HUB_CACHE=str(work / "hf/hub"),
        TORCH_HOME=str(work / "torch"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
        TOKENIZERS_PARALLELISM="false",
        DO_NOT_TRACK="1",
        OMP_NUM_THREADS="4",
        MKL_NUM_THREADS="4",
    )
    return env


class ModelProcess:
    def __init__(self, spec, cache_root: Path):
        self.spec = spec
        self.cache_root = cache_root
        self.process = None
        self.creation = None
        self.logs = None
        self.temp = None
        self.closed = False
        self._closing = None

    async def start(self):
        self.temp = tempfile.TemporaryDirectory(prefix="model-", dir=self.cache_root)
        work = Path(self.temp.name)
        self.creation = asyncio.create_task(
            asyncio.create_subprocess_exec(
                self.spec.python,
                "-I",
                "-B",
                str(CHILD),
                cwd=work,
                env=environment(work),
                start_new_session=True,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=65536,
            )
        )
        try:
            self.process = await asyncio.shield(self.creation)
            self.logs = asyncio.create_task(self._drain_logs())
            await send(self.process.stdin, asdict(self.spec))
            response = await self._receive()
            if response != {"status": "ready", "binding": self.spec.binding}:
                raise WorkerFailure("model_load_failed")
        except BaseException:
            await finish_cleanup(asyncio.create_task(self.close()))
            raise

    async def _drain_logs(self):
        # Consume continuously; never retain or relay prompts/vendor tracebacks.
        total = 0
        while part := await self.process.stderr.read(16384):
            total += len(part)
            if total > 4 * 1024 * 1024:
                return "log_capacity_exceeded"
        return "worker_exited"

    async def _receive(self):
        read = asyncio.create_task(receive(self.process.stdout))
        try:
            done, _ = await asyncio.wait(
                {read, self.logs}, return_when=asyncio.FIRST_COMPLETED
            )
            if read in done:
                return read.result()
            raise WorkerFailure(self.logs.result())
        finally:
            if not read.done():
                read.cancel()
            await finish_cleanup(asyncio.create_task(_drain(read)))

    async def run(self, task):
        try:
            await send(self.process.stdin, task)
            result = await self._receive()
            if (
                not isinstance(result, dict)
                or result.get("id") != task["id"]
                or result.get("binding") != self.spec.binding
            ):
                raise ProtocolError("worker_response_identity_mismatch")
            if result.get("status") == "completed":
                validate_output(
                    task, result.get("values"), dimension=self.spec.dimension
                )
            elif (
                result.get("status") != "rejected"
                or result.get("code") != "input_exceeds_model_tokens"
            ):
                raise WorkerFailure("model_inference_failed")
            return result
        except BaseException:
            await finish_cleanup(asyncio.create_task(self.close()))
            raise

    async def close(self):
        # Concurrent cleanup callers await one owned operation. A failed cleanup
        # remains failed; it cannot become a successful no-op and free capacity.
        if self._closing is None:
            self._closing = asyncio.create_task(self._close_owned())
        await finish_cleanup(self._closing)

    async def _close_owned(self):
        try:
            if self.process is None and self.creation is not None:
                try:
                    self.process = await finish_cleanup(self.creation)
                except (OSError, ValueError):
                    pass
            if self.process is not None:
                # Paused pipe transports can keep Process.wait pending after exit.
                # Drain both pipes while reaping; discard bytes, never retain logs.
                if self.logs is not None:
                    self.logs.cancel()
                    await finish_cleanup(asyncio.create_task(_drain(self.logs)))

                async def discard(stream):
                    while await stream.read(16384):
                        pass

                drains = [
                    asyncio.create_task(discard(stream))
                    for stream in (self.process.stdout, self.process.stderr)
                ]
                try:
                    await finish_cleanup(
                        asyncio.create_task(stop_process_group(self.process, 1))
                    )
                finally:
                    for task in drains:
                        task.cancel()

                    async def drain_all():
                        await asyncio.gather(*drains, return_exceptions=True)

                    await finish_cleanup(asyncio.create_task(drain_all()))
        finally:
            if self.logs is not None:
                self.logs.cancel()
                await finish_cleanup(asyncio.create_task(_drain(self.logs)))
        # Preserve the workspace and reservation when termination was not
        # confirmed. Deleting files underneath a possibly live model is unsafe.
        if self.temp is not None:
            self.temp.cleanup()
        self.closed = True


async def _drain(task):
    await asyncio.gather(task, return_exceptions=True)
