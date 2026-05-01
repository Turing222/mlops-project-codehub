"""Redis client singleton.

职责：为应用代码提供按需初始化的主 Redis 连接。
边界：TaskIQ broker 使用独立配置，不通过本模块创建。
副作用：连接会在首次 init 时建立，应用关闭时应调用 close。
"""

import redis.asyncio as redis

from backend.core.config import settings


class RedisClient:
    """按需创建并缓存 redis.asyncio 客户端。"""

    def __init__(self) -> None:
        self.client: redis.Redis | None = None

    async def init(self) -> redis.Redis:
        if not self.client:
            self.client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
        return self.client

    async def close(self) -> None:
        if self.client:
            await self.client.close()


redis_client = RedisClient()
