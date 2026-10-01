"""Linux/WSL2 local-only IPC with same-UID peers and bounded connections."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import socket
import stat

from app.core.isolated_process import finish_cleanup
from .broker import Broker
from .protocol import receive, request, send, same_user


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise PermissionError(
            "local_inference_directory_requires_owner_only_permissions"
        )


class Server:
    def __init__(self, config, *, broker=None):
        self.config = config
        self.broker = broker or Broker(config)
        self.tasks: set[asyncio.Task] = set()
        self.listener = None
        self.lock = None
        self.inode = None
        self.closing = False

    async def start(self):
        if not hasattr(socket, "SO_PEERCRED"):
            raise RuntimeError("local_inference_requires_linux_or_wsl2")
        import fcntl

        path = Path(self.config.socket_path)
        private_directory(path.parent)
        private_directory(Path(self.config.cache_root))
        flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
        self.lock = os.open(str(path) + ".lock", flags, 0o600)
        info = os.fstat(self.lock)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            os.close(self.lock)
            self.lock = None
            raise PermissionError("unsafe_broker_lock")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if path.exists() or path.is_symlink():
                info = path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise PermissionError("refuse_to_replace_non_socket")
                path.unlink()
            self.listener = await asyncio.start_unix_server(
                self._connected,
                path=path,
                limit=65536,
                backlog=self.config.max_connections,
            )
            path.chmod(0o600)
            self.inode = path.stat().st_ino
            self.broker.start()
        except BaseException:
            await self.close()
            raise

    def _connected(self, reader, writer):
        if (
            self.closing
            or len(self.tasks) >= self.config.max_connections
            or not same_user(writer.get_extra_info("socket"))
        ):
            writer.close()
            return
        task = asyncio.create_task(self._serve(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _serve(self, reader, writer):
        job, disconnected = None, None
        try:
            async with asyncio.timeout(5):
                raw = await receive(reader)
            if raw == {"version": 1, "operation": "status"}:
                async with asyncio.timeout(5):
                    await send(writer, {"version": 1, **self.broker.snapshot()})
                return
            task = request(raw)
            job = self.broker.submit(task)
            # Additional bytes or EOF cancel this one-request connection.
            disconnected = asyncio.create_task(reader.read(1))
            done, _ = await asyncio.wait(
                {job.future, disconnected}, return_when=asyncio.FIRST_COMPLETED
            )
            if job.future in done:
                async with asyncio.timeout(5):
                    await send(writer, job.future.result())
            else:
                self.broker.cancel(job)
        except (Exception, asyncio.CancelledError):
            if job is not None and not job.future.done():
                self.broker.cancel(job)
            # Do not invent a rejection after a dispatch or expose input/logs.
        finally:
            if disconnected is not None:
                disconnected.cancel()
                await asyncio.gather(disconnected, return_exceptions=True)
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError):
                pass

    async def close(self):
        self.closing = True
        if self.listener:
            self.listener.close()
        for task in list(self.tasks):
            task.cancel()

        async def drain():
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
            await self.broker.close()
            if self.listener:
                await self.listener.wait_closed()

        await finish_cleanup(asyncio.create_task(drain()))
        path = Path(self.config.socket_path)
        if (
            self.inode is not None
            and path.exists()
            and path.lstat().st_ino == self.inode
        ):
            path.unlink()
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
