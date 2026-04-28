import redis.asyncio as redis
from app.core.config import settings

# Global redis pool
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

async def get_redis():
    yield redis_client
