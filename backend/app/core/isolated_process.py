"""Bounded, reaped POSIX jobs for trusted local-model diagnostics.

This is process lifecycle isolation, not an OS security sandbox or a GPU memory
scheduler. No shell is used. On cancellation a job retains ownership until its
process group has been stopped and its direct child reaped. WSL2 is supported;
Windows-native tree management needs a Job Object implementation, not kill().
"""

from __future__ import annotations

import asyncio
import math
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


class IsolatedProcessError(RuntimeError):
    """A content-free diagnostic code; never incorporates child logs or input."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float


async def finish_cleanup(task: asyncio.Task):
    """Repeated cancellation cannot orphan the process during cleanup."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


def _signal_group(process: asyncio.subprocess.Process, value: signal.Signals) -> None:
    try:
        os.killpg(process.pid, value)
    except ProcessLookupError:
        pass


async def stop_process_group(process: asyncio.subprocess.Process, grace: float) -> None:
    _signal_group(process, signal.SIGTERM)
    try:
        await asyncio.wait_for(asyncio.shield(process.wait()), grace)
    except TimeoutError:
        pass
    finally:
        # A model subprocess may leave descendants even after its own exit.
        _signal_group(process, signal.SIGKILL)
        await process.wait()


async def run_isolated(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    input_data: bytes = b"",
    timeout_seconds: float = 120,
    max_output_bytes: int = 262144,
    kill_grace_seconds: float = 1,
) -> ProcessResult:
    """Run one trusted local command with an explicit environment and deadline.

    The output budget is shared by stdout and stderr, including logs. Input is
    bounded and supplied through stdin, not a command line containing secrets.
    The caller decides how to validate/output results; raw logs aren't safe to
    expose to a user. The deadline may be followed by bounded termination grace.
    A new interpreter avoids inheriting an initialized CUDA runtime by fork.
    """
    if os.name != "posix":
        raise IsolatedProcessError("isolated_probe_requires_linux_or_wsl")
    if (
        isinstance(argv, (str, bytes))
        or not 1 <= len(argv) <= 64
        or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
        or sum(len(arg) for arg in argv) > 32768
    ):
        raise ValueError("invalid_process_argv")
    for value in (timeout_seconds, kill_grace_seconds):
        if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
            raise ValueError("invalid_process_deadline")
    if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= 16 * 1024**2:
        raise ValueError("invalid_process_output_limit")
    if not isinstance(input_data, bytes) or len(input_data) > 65536:
        raise ValueError("invalid_process_input")

    started = time.monotonic()
    process = None
    tasks: list[asyncio.Task] = []
    creation = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(env),
            cwd=str(cwd),
            start_new_session=True,
            limit=65536,
        )
    )
    received = 0

    async def read(stream: asyncio.StreamReader) -> bytes:
        nonlocal received
        parts = []
        while chunk := await stream.read(16384):
            received += len(chunk)
            if received > max_output_bytes:
                raise IsolatedProcessError("process_output_limit")
            parts.append(chunk)
        return b"".join(parts)

    async def write() -> None:
        assert process is not None and process.stdin is not None
        try:
            process.stdin.write(input_data)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()

    try:
        async with asyncio.timeout(timeout_seconds):
            # Shield creation: cancellation in this await must not lose the pid.
            process = await asyncio.shield(creation)
            assert process.stdout is not None and process.stderr is not None
            tasks = [
                asyncio.create_task(read(process.stdout)),
                asyncio.create_task(read(process.stderr)),
                asyncio.create_task(write()),
                asyncio.create_task(process.wait()),
            ]
            stdout, stderr, _, code = await asyncio.gather(*tasks)
            return ProcessResult(code, stdout, stderr, time.monotonic() - started)
    except TimeoutError:
        raise IsolatedProcessError("process_deadline_exceeded") from None
    except OSError:
        raise IsolatedProcessError("process_start_failed") from None
    finally:
        # Even a cancelled spawn may have produced a running child.
        try:
            if process is None:
                try:
                    process = await finish_cleanup(creation)
                except OSError:
                    process = None
            if process is not None:
                await finish_cleanup(
                    asyncio.create_task(stop_process_group(process, kill_grace_seconds))
                )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:

                async def drain() -> None:
                    await asyncio.gather(*tasks, return_exceptions=True)

                await finish_cleanup(asyncio.create_task(drain()))
