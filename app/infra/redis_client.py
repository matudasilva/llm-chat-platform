import redis.asyncio as redis
from app.core.settings import settings

redis_client = redis.from_url(settings.redis_url, decode_responses=True)

async def test_redis_connection() -> None:
    pong = await redis_client.ping()
    if pong is not True:
        raise RuntimeError("Redis PING failed")
