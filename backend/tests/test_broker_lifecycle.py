"""Real private IPC; deterministic model stand-in stays entirely in tests."""

import asyncio
import sys
import pytest
from app.local_inference.broker import Broker
from app.local_inference.client import (
    Client,
    LocalInferenceNotStarted,
    make_audio_request,
)
from app.local_inference.config import BrokerConfig, ModelSpec
from app.local_inference.server import Server

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="production broker requires Linux peer credentials"
)


class ObservationProcess:
    def __init__(self, spec, cache):
        self.closed = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def start(self):
        pass

    async def run(self, task):
        self.started.set()
        await self.release.wait()
        return {
            "id": task["id"],
            "binding": task["binding"],
            "status": "completed",
            "values": {"regular": [], "exclusive": [], "speakers": []},
        }

    async def close(self):
        self.closed = True
        self.release.set()


@pytest.fixture
def config(tmp_path):
    weights = tmp_path / "weights"
    weights.mkdir()
    spec = ModelSpec(
        "diarization",
        "contract/model",
        str(weights),
        sys.executable,
        dimension=1,
        max_tokens=4096,
    )
    return BrokerConfig(
        str(tmp_path / "private" / "s.sock"), str(tmp_path / "cache"), (spec,)
    )


@pytest.mark.asyncio
async def test_disconnect_cancels_and_reaps_the_owned_model(config):
    processes = []

    def factory(spec, cache):
        process = ObservationProcess(spec, cache)
        processes.append(process)
        return process

    broker = Broker(config, factory=factory)
    server = Server(config, broker=broker)
    await server.start()
    task = make_audio_request(
        "diarization", config.models[0].binding, bytes(320), max_speakers=2
    )
    pending = asyncio.create_task(Client(config.socket_path).acall(task, dimension=1))
    try:
        async with asyncio.timeout(3):
            while not processes:
                await asyncio.sleep(0.01)
            await processes[0].started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        async with asyncio.timeout(3):
            while not processes[0].closed:
                await asyncio.sleep(0.01)
        assert processes[0].closed
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_wrong_model_binding_never_starts_inference(config):
    def forbidden(*args):
        pytest.fail("rejected binding must not dispatch a model")

    server = Server(config, broker=Broker(config, factory=forbidden))
    await server.start()
    try:
        task = make_audio_request("diarization", "f" * 64, bytes(320), max_speakers=2)
        with pytest.raises(LocalInferenceNotStarted):
            await Client(config.socket_path).acall(task, dimension=1)
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_completed_silence_is_an_empty_observation_not_a_fake_speaker(config):
    def ready(spec, cache):
        process = ObservationProcess(spec, cache)
        process.release.set()
        return process

    server = Server(config, broker=Broker(config, factory=ready))
    await server.start()
    try:
        task = make_audio_request(
            "diarization", config.models[0].binding, bytes(320), max_speakers=1
        )
        assert await Client(config.socket_path).acall(task, dimension=1) == {
            "regular": [],
            "exclusive": [],
            "speakers": [],
        }
    finally:
        await server.close()
