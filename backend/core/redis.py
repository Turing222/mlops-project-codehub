import redis.asyncio as redis
from backend.core.config import settings

class RedisClient:
    def __init__(self):
        self.client: redis.Redis | None = None

    async def init(self):
        if not self.client:
            self.client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                decode_responses=True
            )
        return self.client

    async def close(self):
        if self.client:
            await self.client.close()

redis_client = RedisClient()
