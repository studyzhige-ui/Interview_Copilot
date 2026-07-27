"""Small, unauthenticated probes for load balancers and container platforms."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.db.database import engine
from app.db.redis import redis_client

router = APIRouter()
_PROBE_TIMEOUT_SECONDS = 2.0


def _check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


async def dependency_status() -> dict[str, str]:
    """Probe only API-critical dependencies; feature services degrade in-place."""

    async def database() -> str:
        await asyncio.to_thread(_check_database)
        return "ok"

    async def redis() -> str:
        await redis_client.ping()
        return "ok"

    async def probe(check) -> str:
        try:
            return await asyncio.wait_for(check(), timeout=_PROBE_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - health output must not leak internals
            return "unavailable"

    database_result, redis_result = await asyncio.gather(
        probe(database),
        probe(redis),
    )
    return {"database": database_result, "redis": redis_result}


@router.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok", "edition": settings.APP_EDITION}


@router.get("/health/ready", include_in_schema=False)
async def readiness():
    dependencies = await dependency_status()
    ready = all(value == "ok" for value in dependencies.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "unavailable",
            "edition": settings.APP_EDITION,
            "dependencies": dependencies,
        },
    )


__all__ = ["dependency_status", "router"]
