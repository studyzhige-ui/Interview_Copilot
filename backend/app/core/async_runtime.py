"""One explicit async runtime per worker process.

Thread-pool task functions submit to this loop and wait. Connection pools,
MCP sessions and native clients therefore have one owner and one shutdown.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from threading import Lock, Thread

_lock = Lock()
_loop = None
_thread = None


def _get_worker_loop():
    global _loop, _thread
    with _lock:
        if _loop is None:
            ready = Future()

            def serve():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                ready.set_result(loop)
                loop.run_forever()
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
                loop.close()

            _thread = Thread(target=serve, name="agent-async-runtime", daemon=True)
            _thread.start()
            _loop = ready.result(timeout=10)
        return _loop


def run_async(coro):
    loop = _get_worker_loop()
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        coro.close()
        raise RuntimeError("run_async cannot block its own event loop")
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def shutdown_worker_runtime():
    global _loop, _thread
    with _lock:
        if _loop is None:
            return

        async def drain():
            from app.agent_runtime.mcp import manager
            from app.core.runtime_resources import close_current_resources

            pending = [
                task
                for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
            ]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            try:
                await manager.close_all()
            finally:
                await close_current_resources()

        asyncio.run_coroutine_threadsafe(drain(), _loop).result(timeout=30)
        _loop.call_soon_threadsafe(_loop.stop)
        _thread.join(timeout=30)
        _loop = None
        _thread = None
