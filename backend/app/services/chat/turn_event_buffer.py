from __future__ import annotations

import json

from app.db.redis import get_redis_client


class TurnEventBuffer:
    ttl_seconds = 3600

    @staticmethod
    def _key(turn_id: str) -> str:
        return f"chat:events:{turn_id}"

    async def ping(self) -> None:
        await get_redis_client().ping()

    async def append(self, turn_id: str, event_json: str) -> str:
        key = self._key(turn_id)
        event_id = await get_redis_client().xadd(
            key,
            {"event": event_json},
            maxlen=10_000,
            approximate=True,
        )
        await get_redis_client().expire(key, self.ttl_seconds)
        return str(event_id)

    async def read(
        self, turn_id: str, cursor: str, *, block_ms: int = 15_000
    ) -> list[tuple[str, str]]:
        rows = await get_redis_client(blocking=True).xread(
            {self._key(turn_id): cursor},
            count=200,
            block=block_ms,
        )
        if not rows:
            return []
        return [
            (str(event_id), fields["event"])
            for _stream, events in rows
            for event_id, fields in events
        ]

    async def reset(self, turn_id: str) -> None:
        """Start a fresh event generation when the same Turn resumes."""
        await get_redis_client().delete(self._key(turn_id))

    @staticmethod
    def is_done(event_json: str) -> bool:
        try:
            return json.loads(event_json).get("type") == "done"
        except (TypeError, ValueError):
            return False


turn_event_buffer = TurnEventBuffer()
