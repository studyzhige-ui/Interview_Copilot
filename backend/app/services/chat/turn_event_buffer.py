from __future__ import annotations

import json

from app.db.redis import redis_client


class TurnEventBuffer:
    ttl_seconds = 3600

    @staticmethod
    def _key(turn_id: str) -> str:
        return f"chat:events:{turn_id}"

    @staticmethod
    def _cancel_key(turn_id: str) -> str:
        return f"chat:cancel:{turn_id}"

    async def ping(self) -> None:
        await redis_client.ping()

    async def append(self, turn_id: str, event_json: str) -> str:
        key = self._key(turn_id)
        event_id = await redis_client.xadd(
            key,
            {"event": event_json},
            maxlen=10_000,
            approximate=True,
        )
        await redis_client.expire(key, self.ttl_seconds)
        return str(event_id)

    async def read(
        self, turn_id: str, cursor: str, *, block_ms: int = 15_000
    ) -> list[tuple[str, str]]:
        rows = await redis_client.xread(
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

    async def request_cancel(self, turn_id: str) -> None:
        key = self._cancel_key(turn_id)
        await redis_client.lpush(key, "cancel")
        await redis_client.expire(key, self.ttl_seconds)

    async def wait_cancel(self, turn_id: str) -> None:
        await redis_client.blpop(self._cancel_key(turn_id), timeout=0)

    @staticmethod
    def is_done(event_json: str) -> bool:
        try:
            return json.loads(event_json).get("type") == "done"
        except (TypeError, ValueError):
            return False


turn_event_buffer = TurnEventBuffer()
