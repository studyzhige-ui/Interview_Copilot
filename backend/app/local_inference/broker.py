"""One process-owned scheduling lane with resident, separately reaped models.

Memory reservations are admission estimates, not a hard VRAM sandbox. Model
weights are shared by API/Celery requests through this broker, not loaded there.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time

from app.core.isolated_process import finish_cleanup
from .config import BrokerConfig
from .process import ModelProcess
from .protocol import PRIORITIES


@dataclass
class Job:
    task: dict
    future: asyncio.Future
    queued: float
    deadline: float
    started: bool = False


class Broker:
    def __init__(self, config: BrokerConfig, *, factory=ModelProcess):
        self.config, self.factory = config, factory
        self.specs = {m.role: m for m in config.models}
        self.pending: list[Job] = []
        self.resident: dict[str, tuple[ModelProcess, float]] = {}
        self.active: Job | None = None
        self.running: asyncio.Task | None = None
        self.loop_task: asyncio.Task | None = None
        self.wake = asyncio.Event()
        self.closed = False
        self.counts = {"completed": 0, "rejected": 0, "unknown": 0}

    def start(self):
        if self.loop_task is not None:
            raise RuntimeError("broker_already_started")
        Path(self.config.cache_root).mkdir(mode=0o700, parents=True, exist_ok=True)
        self.loop_task = asyncio.create_task(self._loop())

    def _error(self, task, status, code):
        return {
            "id": task["id"],
            "binding": task["binding"],
            "status": status,
            "code": code,
        }

    def submit(self, task: dict) -> Job:
        now = time.monotonic()
        job = Job(
            task, asyncio.get_running_loop().create_future(), now, now + task["timeout"]
        )
        spec = self.specs.get(task["role"])
        code = None
        if self.closed:
            code = "broker_stopping"
        elif spec is None or task["binding"] != spec.binding:
            code = "model_binding_mismatch"
        elif any(
            j.task["id"] == task["id"]
            for j in [*self.pending, *([self.active] if self.active else [])]
        ):
            code = "duplicate_request"
        elif len(self.pending) + (self.active is not None) >= self.config.max_pending:
            code = "queue_full"
        if code:
            self.counts["rejected"] += 1
            job.future.set_result(self._error(task, "not_started", code))
        else:
            self.pending.append(job)
            self.wake.set()
        return job

    def cancel(self, job: Job):
        if job in self.pending:
            self.pending.remove(job)
            job.future.cancel()
        elif self.active is job and self.running is not None:
            self.running.cancel()
        self.wake.set()

    async def _drop(self, role):
        entry = self.resident.get(role)
        if entry is not None:
            # Do not release the reservation before process-group cleanup.
            await finish_cleanup(asyncio.create_task(entry[0].close()))
            self.resident.pop(role, None)

    def reserved(self):
        return sum(
            self.specs[role].reservation_mib
            for role in self.resident
            if self.specs[role].device == "cuda"
        )

    async def _model(self, role):
        if role in self.resident:
            return self.resident[role][0]
        spec = self.specs[role]
        amount = spec.reservation_mib if spec.device == "cuda" else 0
        while self.reserved() + amount > self.config.capacity_mib:
            oldest = min(self.resident, key=lambda key: self.resident[key][1])
            await self._drop(oldest)
        process = self.factory(spec, Path(self.config.cache_root))
        self.resident[role] = (process, time.monotonic())
        try:
            async with asyncio.timeout(self.config.load_timeout):
                await process.start()
        except BaseException:
            await self._drop(role)
            raise
        return process

    async def _execute(self, job):
        try:
            async with asyncio.timeout_at(job.deadline):
                model = await self._model(job.task["role"])
                job.started = True
                result = await model.run(job.task)
            self.resident[job.task["role"]] = (model, time.monotonic())
            self.counts[
                "completed" if result["status"] == "completed" else "rejected"
            ] += 1
            return result
        except BaseException as exc:
            if not isinstance(exc, (Exception, asyncio.CancelledError)):
                raise
            await self._drop(job.task["role"])
            outcome = "unknown" if job.started else "not_started"
            self.counts["unknown" if job.started else "rejected"] += 1
            return self._error(
                job.task,
                outcome,
                "execution_interrupted" if job.started else "model_not_available",
            )

    async def _loop(self):
        try:
            while not self.closed:
                now = time.monotonic()
                for job in self.pending[:]:
                    if job.deadline <= now:
                        self.pending.remove(job)
                        self.counts["rejected"] += 1
                        if not job.future.done():
                            job.future.set_result(
                                self._error(job.task, "not_started", "queue_deadline")
                            )
                if self.pending:
                    # Aging eventually promotes background work. No unsafe hard
                    # preemption of a CUDA kernel to accommodate new arrivals.
                    job = min(
                        self.pending,
                        key=lambda j: (
                            PRIORITIES[j.task["priority"]] - (now - j.queued) / 5,
                            j.queued,
                        ),
                    )
                    self.pending.remove(job)
                    self.active = job
                    self.running = asyncio.create_task(self._execute(job))
                    try:
                        result = await self.running
                    except asyncio.CancelledError:
                        # cancel() can arrive before _execute has entered its try.
                        result = self._error(
                            job.task, "not_started", "cancelled_before_start"
                        )
                    if not job.future.done():
                        job.future.set_result(result)
                    self.active, self.running = None, None
                    continue
                for role, (_, used) in list(self.resident.items()):
                    if now - used >= self.config.idle_seconds:
                        await self._drop(role)
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), 1)
                except TimeoutError:
                    pass
        finally:
            for role in list(self.resident):
                await self._drop(role)

    async def close(self):
        self.closed = True
        for job in self.pending:
            if not job.future.done():
                job.future.set_result(
                    self._error(job.task, "not_started", "broker_stopping")
                )
        self.pending.clear()
        if self.running is not None:
            self.running.cancel()
        self.wake.set()
        if self.loop_task is not None:
            await finish_cleanup(self.loop_task)

    def snapshot(self):
        return {
            "pending": len(self.pending),
            "active": self.active is not None,
            "resident_roles": sorted(self.resident),
            "reserved_mib": self.reserved(),
            "closing": self.closed,
            **self.counts,
        }
