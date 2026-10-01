from __future__ import annotations

import asyncio
import os
import sys

import pytest

from app.core.isolated_process import IsolatedProcessError, run_isolated
from tests.process_assertions import process_stopped

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="Linux/WSL process group contract"
)


def command(code):
    # Synthetic children only need stdlib. Site hooks are unrelated to the
    # lifecycle contract and can consume the entire short deadline on CI.
    return [sys.executable, "-I", "-S", "-B", "-c", code]


async def execute(tmp_path, code, **kwargs):
    return await run_isolated(
        command(code), env={"PATH": os.environ.get("PATH", "")}, cwd=tmp_path, **kwargs
    )


def alive(pid):
    if sys.platform.startswith("linux"):
        return not process_stopped(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def wait_path(path):
    async with asyncio.timeout(5):
        while not path.exists():
            await asyncio.sleep(0.01)
    return int(path.read_text())


async def test_both_streams_and_input(tmp_path):
    result = await execute(
        tmp_path,
        "import sys; print(sys.stdin.read()); print('warning',file=sys.stderr)",
        input_data=b"synthetic",
    )
    assert result.returncode == 0 and result.stdout == b"synthetic\n"
    assert result.stderr == b"warning\n"


async def test_does_not_inherit_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATE_TEST_CREDENTIAL", "secret-sentinel")
    result = await execute(
        tmp_path, "import os; print(os.environ.get('PRIVATE_TEST_CREDENTIAL','absent'))"
    )
    assert result.stdout == b"absent\n"


async def test_nonzero_exit_retained(tmp_path):
    result = await execute(tmp_path, "import sys; sys.exit(7)")
    assert result.returncode == 7


async def test_timeout_reaps_child_ignoring_term(tmp_path):
    path = tmp_path / "pid"
    code = f"import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM, signal.SIG_IGN); Path({str(path)!r}).write_text(str(os.getpid())); time.sleep(60)"
    with pytest.raises(IsolatedProcessError, match="deadline"):
        await execute(tmp_path, code, timeout_seconds=0.4, kill_grace_seconds=0.05)
    assert not alive(int(path.read_text()))


async def test_repeated_cancel_waits_for_reap(tmp_path):
    path = tmp_path / "pid"
    code = f"import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM, signal.SIG_IGN); Path({str(path)!r}).write_text(str(os.getpid())); time.sleep(60)"
    task = asyncio.create_task(execute(tmp_path, code, kill_grace_seconds=0.1))
    pid = await wait_path(path)
    task.cancel()
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not alive(pid)


async def test_output_limit_combines_stdout_and_stderr(tmp_path):
    with pytest.raises(IsolatedProcessError, match="output_limit"):
        await execute(
            tmp_path,
            "import sys; sys.stdout.write('x'*700); sys.stderr.write('y'*700)",
            max_output_bytes=1024,
        )


async def test_flooding_writer_is_reaped(tmp_path):
    path = tmp_path / "pid"
    code = f"import os; from pathlib import Path; Path({str(path)!r}).write_text(str(os.getpid()))\nwhile True: os.write(1, b'x'*4096)"
    with pytest.raises(IsolatedProcessError, match="output_limit"):
        await execute(tmp_path, code, max_output_bytes=1024)
    assert not alive(int(path.read_text()))


async def test_descendant_holding_pipe_cannot_outlive_job(tmp_path):
    path = tmp_path / "descendant"
    nested = f"import os,time; from pathlib import Path; Path({str(path)!r}).write_text(str(os.getpid())); time.sleep(60)"
    code = f"import subprocess,sys; subprocess.Popen([sys.executable,'-I','-S','-B','-c',{nested!r}])"
    with pytest.raises(IsolatedProcessError, match="deadline"):
        await execute(tmp_path, code, timeout_seconds=0.5, kill_grace_seconds=0.05)
    # SIGKILL delivery to an orphaned descendant is asynchronous; the direct
    # child is already reaped, and the descendant must stop within this bound.
    async with asyncio.timeout(2):
        while alive(int(path.read_text())):
            await asyncio.sleep(0.01)


async def test_cancel_during_spawn_still_owns_child(tmp_path, monkeypatch):
    original = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    children = []

    async def delayed(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        spawned.set()
        await asyncio.sleep(0.05)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    task = asyncio.create_task(
        execute(tmp_path, "import time; time.sleep(60)", kill_grace_seconds=0.05)
    )
    await asyncio.wait_for(spawned.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(children) == 1 and children[0].returncode is not None
    assert not alive(children[0].pid)


@pytest.mark.parametrize(
    "options",
    [
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
        {"kill_grace_seconds": -1},
        {"max_output_bytes": 0},
        {"max_output_bytes": True},
        {"input_data": b"x" * 65537},
    ],
)
async def test_invalid_limits_rejected_before_spawn(tmp_path, options):
    with pytest.raises(ValueError):
        await execute(tmp_path, "raise AssertionError('should not start')", **options)


async def test_start_error_is_content_free(tmp_path):
    with pytest.raises(IsolatedProcessError) as caught:
        await run_isolated(["/not-present/secret-sentinel"], cwd=tmp_path, env={})
    assert str(caught.value) == "process_start_failed"
