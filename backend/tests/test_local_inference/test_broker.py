import asyncio
from dataclasses import replace

from app.local_inference.broker import Broker
from .conftest import task


class FakeProcess:
    instances = []
    entered = None
    release = None
    events = []
    fail = False

    def __init__(self, spec, _cache):
        self.spec = spec
        self.closed = False
        self.instances.append(self)

    async def start(self):
        self.events.append(("load", self.spec.role))

    async def run(self, request):
        self.events.append(("run", request["id"]))
        if self.entered:
            self.entered.set()
        if self.release:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("private content must not escape")
        values = (
            [[1.0, 0.0, 0.0] for _ in request["texts"]]
            if self.spec.role == "embedding"
            else [1.0 for _ in request["texts"]]
        )
        return dict(
            id=request["id"],
            binding=self.spec.binding,
            status="completed",
            values=values,
        )

    async def close(self):
        self.events.append(("closed", self.spec.role))
        self.closed = True


def factory():
    class P(FakeProcess):
        instances = []
        events = []
        entered = None
        release = None
        fail = False

    return P


async def test_resident_reuse_and_output(config):
    P = factory()
    broker = Broker(config, factory=P)
    broker.start()
    try:
        for _ in range(2):
            assert (await broker.submit(task(config.models[0])).future)[
                "status"
            ] == "completed"
        assert len(P.instances) == 1
        assert broker.snapshot()["completed"] == 2
    finally:
        await broker.close()
    assert all(p.closed for p in P.instances)


async def test_pending_cancel_never_executes_and_priority_is_real(config):
    P = factory()
    P.entered = asyncio.Event()
    P.release = asyncio.Event()
    broker = Broker(config, factory=P)
    broker.start()
    try:
        first = broker.submit(task(config.models[0]))
        await P.entered.wait()
        background = broker.submit(task(config.models[0], priority="background"))
        cancelled = broker.submit(task(config.models[0]))
        broker.cancel(cancelled)
        interactive = broker.submit(task(config.models[0]))
        P.release.set()
        await asyncio.gather(first.future, background.future, interactive.future)
        runs = [item[1] for item in P.events if item[0] == "run"]
        assert runs == [first.task["id"], interactive.task["id"], background.task["id"]]
        assert cancelled.future.cancelled()
    finally:
        await broker.close()


async def test_backpressure_and_binding_rejection(config):
    P = factory()
    P.entered = asyncio.Event()
    P.release = asyncio.Event()
    broker = Broker(replace(config, max_pending=1), factory=P)
    broker.start()
    try:
        first = broker.submit(task(config.models[0]))
        await P.entered.wait()
        assert (await broker.submit(task(config.models[0])).future)[
            "code"
        ] == "queue_full"
        altered = {**task(config.models[0]), "binding": "0" * 64}
        assert (await broker.submit(altered).future)["code"] == "model_binding_mismatch"
        duplicate = broker.submit(first.task)
        assert (await duplicate.future)["code"] == "duplicate_request"
        broker.cancel(first)
        assert (await first.future)["status"] == "unknown"
        assert P.instances[0].closed
    finally:
        await broker.close()


async def test_failure_does_not_break_lane(config):
    P = factory()
    P.fail = True
    broker = Broker(config, factory=P)
    broker.start()
    try:
        assert (await broker.submit(task(config.models[0])).future)[
            "status"
        ] == "unknown"
        assert not broker.resident
        P.fail = False
        assert (await broker.submit(task(config.models[0])).future)[
            "status"
        ] == "completed"
        assert len(P.instances) == 2
    finally:
        await broker.close()


async def test_deadline_reaps_before_next_request(config):
    P = factory()
    P.entered = asyncio.Event()
    P.release = asyncio.Event()
    broker = Broker(config, factory=P)
    broker.start()
    try:
        first = broker.submit(task(config.models[0], timeout=0.03))
        await P.entered.wait()
        assert (await first.future)["status"] == "unknown"
        assert P.instances[0].closed
        P.release.set()
        assert (await broker.submit(task(config.models[0])).future)[
            "status"
        ] == "completed"
        assert P.events.index(("closed", "embedding")) < len(P.events) - 1
    finally:
        await broker.close()


async def test_memory_eviction_closes_old_worker(config):
    P = factory()
    config = replace(
        config, models=tuple(replace(m, device="cuda") for m in config.models)
    )
    broker = Broker(config, factory=P)
    broker.start()
    try:
        await broker.submit(task(config.models[0])).future
        assert broker.reserved() == 20
        await broker.submit(task(config.models[1])).future
        assert broker.reserved() == 20 and P.instances[0].closed
        assert P.events.index(("closed", "embedding")) < P.events.index(
            ("load", "reranking")
        )
    finally:
        await broker.close()


async def test_close_rejects_queue_and_reaps_active(config):
    P = factory()
    P.entered = asyncio.Event()
    P.release = asyncio.Event()
    broker = Broker(config, factory=P)
    broker.start()
    first = broker.submit(task(config.models[0]))
    await P.entered.wait()
    second = broker.submit(task(config.models[1]))
    await broker.close()
    assert (await first.future)["status"] == "unknown"
    assert (await second.future)["status"] == "not_started"
    assert broker.reserved() == 0 and not broker.resident
    assert (await broker.submit(task(config.models[0])).future)[
        "status"
    ] == "not_started"


async def test_background_aging_and_queued_deadline(config):
    import time

    P = factory()
    P.entered, P.release = asyncio.Event(), asyncio.Event()
    broker = Broker(config, factory=P)
    broker.start()
    try:
        first = broker.submit(task(config.models[0]))
        await P.entered.wait()
        expired = broker.submit(task(config.models[0]))
        expired.deadline = time.monotonic() - 1
        background = broker.submit(task(config.models[0], priority="background"))
        background.queued -= 60
        interactive = broker.submit(task(config.models[0]))
        P.release.set()
        await asyncio.gather(
            first.future, expired.future, background.future, interactive.future
        )
        assert expired.future.result()["code"] == "queue_deadline"
        runs = [entry[1] for entry in P.events if entry[0] == "run"]
        assert runs == [first.task["id"], background.task["id"], interactive.task["id"]]
    finally:
        await broker.close()


async def test_idle_resident_is_reaped(config):
    import time

    P = factory()
    broker = Broker(config, factory=P)
    broker.start()
    try:
        await broker.submit(task(config.models[0])).future
        model, _ = broker.resident["embedding"]
        broker.resident["embedding"] = (model, time.monotonic() - 10)
        broker.wake.set()
        async with asyncio.timeout(3):
            while broker.resident:
                await asyncio.sleep(0.01)
        assert model.closed
    finally:
        await broker.close()


async def test_queued_deadline_returns_before_active_finishes(config):
    P = factory()
    P.entered, P.release = asyncio.Event(), asyncio.Event()
    broker = Broker(config, factory=P)
    broker.start()
    try:
        active = broker.submit(task(config.models[0]))
        await P.entered.wait()
        queued = broker.submit(task(config.models[0], timeout=0.02))
        response = await asyncio.wait_for(queued.future, 0.5)
        assert response["code"] == "queue_deadline"
        assert not active.future.done() and not broker.pending
        P.release.set()
        await active.future
        assert [v for event, v in P.events if event == "run"] == [active.task["id"]]
    finally:
        await broker.close()


async def test_teardown_failure_faults_broker_and_resolves_waiters(config):
    class BrokenClose(FakeProcess):
        events, instances = [], []
        release, entered = asyncio.Event(), asyncio.Event()

        async def close(self):
            raise RuntimeError("native cleanup not confirmed")

    gpu_config = replace(
        config, models=tuple(replace(m, device="cuda") for m in config.models)
    )
    broker = Broker(gpu_config, factory=BrokenClose)
    broker.start()
    try:
        first = broker.submit(task(gpu_config.models[0], timeout=0.03))
        await BrokenClose.entered.wait()
        next_job = broker.submit(task(gpu_config.models[1]))
        assert (await asyncio.wait_for(first.future, 0.5))["status"] == "unknown"
        assert (await asyncio.wait_for(next_job.future, 0.5))["status"] == "not_started"
        assert broker.snapshot()["faulted"] is True
        assert broker.reserved() == gpu_config.models[0].reservation_mib
        assert (await broker.submit(task(gpu_config.models[1])).future)[
            "code"
        ] == "broker_stopping"
    finally:
        await broker.close()
