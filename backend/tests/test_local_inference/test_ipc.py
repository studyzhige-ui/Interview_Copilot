"""Real Unix connections and fresh Python children, without real ML weights."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from app.local_inference.client import (
    Client,
    LocalInferenceNotStarted,
    LocalInferenceUnknown,
)
from app.local_inference.server import Server
from app.local_inference import process
from tests.process_assertions import process_stopped
from .conftest import task

# This test-owned executable obeys the actual framing protocol. Production has
# no fake backend, plugin import string, or environment switch enabling it.
FAKE = r"""
import json,os,struct,sys,time

def read():
    n=struct.unpack('!I',sys.stdin.buffer.read(4))[0]
    return json.loads(sys.stdin.buffer.read(n))
def write(value):
    raw=json.dumps(value).encode()
    sys.stdout.buffer.write(struct.pack('!I',len(raw))+raw)
    sys.stdout.buffer.flush()
spec=read()
# The binding algorithm must match the production config module.
import hashlib
v=['sentence-transformer-explicit-prompts-v1',spec['role'],spec['model_id'],spec['revision'],spec['dimension'],spec['max_tokens'],spec['query_prefix'],spec['text_prefix']]
binding=hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
from pathlib import Path
root=Path(spec['model_path'])
(root/'pid').write_text(str(os.getpid()))
(root/'env.json').write_text(json.dumps(dict(os.environ)))
write({'status':'ready','binding':binding})
while True:
    try: job=read()
    except Exception: break
    text=job['texts'][0]
    if text=='hang':
        (root/'started').write_text('yes')
        time.sleep(100)
    if text=='flood':
        sys.stdout.buffer.write(struct.pack('!I',2000000000)); sys.stdout.buffer.flush(); time.sleep(100)
    if text=='logflood':
        sys.stderr.buffer.write(b'x'*(5*1024*1024)); sys.stderr.buffer.flush(); time.sleep(100)
    if text=='crash': os._exit(2)
    value=[[1.,0.,0.] for _ in job['texts']] if job['role']=='embedding' else [1. for _ in job['texts']]
    write({'status':'completed','id':job['id'],'binding':binding,'values':value})
"""


@pytest.fixture
def fake_child(tmp_path, monkeypatch):
    file = tmp_path / "child.py"
    file.write_text(FAKE)
    monkeypatch.setattr(process, "CHILD", file)
    return file


async def eventually(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_real_ipc_sync_async_reuse_and_private_environment(
    config, fake_child, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-inherit")
    monkeypatch.setenv("DATABASE_URL", "private-database")
    monkeypatch.setenv("HTTP_PROXY", "private-proxy")
    server = Server(config)
    await server.start()
    try:
        client = Client(config.socket_path, timeout=3)
        assert await client.acall(task(config.models[0]), dimension=3) == [
            [1.0, 0.0, 0.0]
        ]
        pid = (Path(config.models[0].model_path) / "pid").read_text()
        assert await asyncio.to_thread(
            client.call, task(config.models[0]), dimension=3
        ) == [[1.0, 0.0, 0.0]]
        assert (Path(config.models[0].model_path) / "pid").read_text() == pid
        env = json.loads((Path(config.models[0].model_path) / "env.json").read_text())
        assert (
            not {"DEEPSEEK_API_KEY", "DATABASE_URL", "HTTP_PROXY", "PYTHONPATH"}
            & env.keys()
        )
        assert env["HF_HUB_OFFLINE"] == "1"
        state = await client.status()
        assert state["completed"] == 2 and state["resident_roles"] == ["embedding"]
        assert oct(os.stat(config.socket_path).st_mode & 0o777) == "0o600"
    finally:
        await server.close()
    assert not Path(config.socket_path).exists()
    assert not list(Path(config.cache_root).iterdir())


async def test_single_owner_lock_does_not_remove_first_socket(config, fake_child):
    one = Server(config)
    two = Server(config)
    await one.start()
    try:
        with pytest.raises(BlockingIOError):
            await two.start()
        assert (await Client(config.socket_path).status())["closing"] is False
    finally:
        await one.close()


async def test_refuse_non_socket_and_unsafe_directory(config, tmp_path):
    path = Path(config.socket_path)
    path.write_text("keep")
    server = Server(config)
    with pytest.raises(PermissionError):
        await server.start()
    assert path.read_text() == "keep"
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(PermissionError):
        await Server(config).start()
    assert path.is_symlink()


async def test_disconnect_cancels_and_reaps_active(config, fake_child):
    server = Server(config)
    await server.start()
    try:
        run = asyncio.create_task(
            Client(config.socket_path).acall(
                task(config.models[0], texts=["hang"], timeout=60), dimension=3
            )
        )
        await eventually(
            lambda: (Path(config.models[0].model_path) / "started").exists()
        )
        pid = int((Path(config.models[0].model_path) / "pid").read_text())
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        await eventually(lambda: server.broker.active is None)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not server.broker.resident
        assert await Client(config.socket_path).acall(
            task(config.models[0]), dimension=3
        ) == [[1.0, 0.0, 0.0]]
    finally:
        await server.close()


@pytest.mark.parametrize("mode", ["flood", "logflood", "crash"])
async def test_bad_worker_is_not_retried_or_leaked(config, fake_child, mode):
    server = Server(config)
    await server.start()
    try:
        with pytest.raises(LocalInferenceUnknown):
            await Client(config.socket_path, timeout=5).acall(
                task(config.models[0], texts=[mode], timeout=3), dimension=3
            )
        pid = int((Path(config.models[0].model_path) / "pid").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not server.broker.resident
    finally:
        await server.close()


async def test_unsupported_binding_is_definite_rejection(config, fake_child):
    server = Server(config)
    await server.start()
    try:
        with pytest.raises(LocalInferenceNotStarted):
            await Client(config.socket_path).acall(
                {**task(config.models[0]), "binding": "1" * 64}, dimension=3
            )
        assert not server.broker.resident
    finally:
        await server.close()


def test_no_service_is_not_implicit_local_or_cloud_fallback(config):
    with pytest.raises(LocalInferenceNotStarted):
        Client(config.socket_path).call(task(config.models[0]), dimension=3)


async def test_deadline_and_repeated_cancel_do_not_leave_child(config, fake_child):
    server = Server(config)
    await server.start()
    try:
        run = asyncio.create_task(
            Client(config.socket_path, timeout=5).acall(
                task(config.models[0], texts=["hang"], timeout=2), dimension=3
            )
        )
        await eventually(
            lambda: (Path(config.models[0].model_path) / "started").exists()
        )
        pid = int((Path(config.models[0].model_path) / "pid").read_text())
        job = server.broker.active
        for _ in range(3):
            server.broker.cancel(job)
            await asyncio.sleep(0)
        with pytest.raises(LocalInferenceUnknown):
            await run
        await eventually(lambda: server.broker.active is None)
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        await server.close()


async def test_client_after_send_timeout_is_unknown_not_free_retry(config, fake_child):
    server = Server(config)
    await server.start()
    try:
        with pytest.raises(LocalInferenceUnknown):
            await Client(config.socket_path, timeout=0.15).acall(
                task(config.models[0], texts=["hang"], timeout=60), dimension=3
            )
        await eventually(lambda: server.broker.active is None)
        assert not server.broker.resident
    finally:
        await server.close()


async def test_parent_death_terminates_resident_child(config, fake_child, tmp_path):
    import subprocess
    import sys

    backend = Path(__file__).resolve().parents[2]
    # Invoke the same production parent-death hook in the protocol fixture.
    source = fake_child.read_text()
    source = source.replace(
        "spec=read()",
        f"sys.path.insert(0, {str(backend)!r})\nfrom app.local_inference.child import bind_parent\nbind_parent()\nspec=read()",
    )
    fake_child.write_text(source)
    cfg = tmp_path / "broker.json"
    cfg.write_text(json.dumps(config.as_dict()))
    boot = tmp_path / "broker.py"
    boot.write_text(f"""
import sys,asyncio
sys.path.insert(0,{str(backend)!r})
from app.local_inference import process
from app.local_inference.config import BrokerConfig
from app.local_inference.server import Server
from pathlib import Path
process.CHILD=Path({str(fake_child)!r})
async def main():
    server=Server(BrokerConfig.load(Path({str(cfg)!r})))
    await server.start()
    await asyncio.Event().wait()
asyncio.run(main())
""")
    parent = subprocess.Popen(
        [sys.executable, "-I", str(boot)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    run = None
    try:
        await eventually(lambda: Path(config.socket_path).exists())
        run = asyncio.create_task(
            Client(config.socket_path, timeout=3).acall(
                task(config.models[0], texts=["hang"]), dimension=3
            )
        )
        await eventually(
            lambda: (Path(config.models[0].model_path) / "started").exists()
        )
        child_pid = int((Path(config.models[0].model_path) / "pid").read_text())
        parent.kill()
        await asyncio.to_thread(parent.wait, 3)
        with pytest.raises(LocalInferenceUnknown):
            await run

        await eventually(lambda: process_stopped(child_pid))
    finally:
        if run and not run.done():
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
        if parent.poll() is None:
            parent.kill()
            await asyncio.to_thread(parent.wait, 3)


@pytest.mark.parametrize("role", ["transcription", "alignment"])
async def test_audio_crosses_real_socket_and_owned_process(config, fake_child, role):
    """Actual server/client/child transport; fixture replaces only model math."""
    from dataclasses import replace
    from app.local_inference.audio import AUDIO_OUTPUT_TOKENS
    from app.local_inference.client import make_audio_request
    from app.local_inference.config import ModelSpec

    spec = ModelSpec(
        role,
        f"Qwen/test-{role}",
        config.models[0].model_path,
        config.models[0].python,
        dimension=1,
        max_tokens=AUDIO_OUTPUT_TOKENS,
        reservation_mib=20,
    )
    config = replace(config, models=(spec,))
    source = FAKE.replace(
        "v=['sentence-transformer-explicit-prompts-v1',",
        "v=[{'transcription':'qwen-asr-transformers-pcm16-v1','alignment':'qwen-forced-aligner-pcm16-v1'}[spec['role']],",
    ).replace("text=job['texts'][0]", "text=job['language']")
    source = source.replace(
        "value=[[1.,0.,0.] for _ in job['texts']] if job['role']=='embedding' else [1. for _ in job['texts']]",
        "value={'text': 'synthetic ASR' if spec['role']=='transcription' else job['text'], 'language':job['language'], 'words': [] if spec['role']=='transcription' else [{'text':job['text'],'start':0.0,'end':0.5}]}",
    )
    fake_child.write_text(source)
    server = Server(config)
    await server.start()
    try:
        client = Client(config.socket_path, timeout=3)
        request = make_audio_request(
            role,
            spec.binding,
            b"\x00\x00" * 16000,
            text="original text" if role == "alignment" else "",
            language="en",
            timeout=3,
        )
        result = await client.acall(request, dimension=1)
        assert result["text"] == (
            "synthetic ASR" if role == "transcription" else "original text"
        )
        assert result["words"] == (
            []
            if role == "transcription"
            else [{"text": "original text", "start": 0.0, "end": 0.5}]
        )
        pid = int((Path(spec.model_path) / "pid").read_text())
        assert await client.acall(request, dimension=1) == result
        assert int((Path(spec.model_path) / "pid").read_text()) == pid
        # Corrupt PCM is rejected before dispatch; the existing process survives.
        request["audio"]["sha256"] = "0" * 64
        with pytest.raises(ValueError):
            await client.acall(request, dimension=1)
        assert (await client.status())["completed"] == 2
    finally:
        await server.close()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not list(Path(config.cache_root).iterdir())


async def test_close_failure_is_sticky_and_keeps_workspace(config, monkeypatch):
    from types import SimpleNamespace

    cleaned, attempts = [], []
    obj = process.ModelProcess(config.models[0], Path(config.cache_root))
    out, err = asyncio.StreamReader(), asyncio.StreamReader()
    out.feed_eof()
    err.feed_eof()
    obj.process = SimpleNamespace(stdout=out, stderr=err)
    obj.temp = SimpleNamespace(cleanup=lambda: cleaned.append(True))

    async def fail_stop(_process, grace):
        attempts.append(grace)
        raise OSError("synthetic stop failure")

    monkeypatch.setattr(process, "stop_process_group", fail_stop)
    for _ in range(2):
        with pytest.raises(OSError, match="synthetic stop failure"):
            await obj.close()
    assert attempts == [1] and not cleaned and obj.closed is False


async def test_concurrent_close_waits_for_same_reap(config, monkeypatch):
    from types import SimpleNamespace

    entered, release = asyncio.Event(), asyncio.Event()
    cleaned, attempts = [], []
    obj = process.ModelProcess(config.models[0], Path(config.cache_root))
    out, err = asyncio.StreamReader(), asyncio.StreamReader()
    out.feed_eof()
    err.feed_eof()
    obj.process = SimpleNamespace(stdout=out, stderr=err)
    obj.temp = SimpleNamespace(cleanup=lambda: cleaned.append(True))

    async def stop(_process, grace):
        attempts.append(grace)
        entered.set()
        await release.wait()

    monkeypatch.setattr(process, "stop_process_group", stop)
    first = asyncio.create_task(obj.close())
    await entered.wait()
    second = asyncio.create_task(obj.close())
    try:
        await asyncio.sleep(0)
        assert not first.done() and not second.done() and not obj.closed
        assert not cleaned
    finally:
        release.set()
        await asyncio.gather(first, second)
    assert obj.closed and attempts == [1] and cleaned == [True]
