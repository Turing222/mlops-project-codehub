import os
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

# 使用环境变量，默认指向 Redis DB 1 作为队列专用（避免和主缓存数据冲突）
REDIS_URL = os.getenv("TASKIQ_REDIS_URL", "redis://redis:6379/1")

# 使用 Redis 的 List 结构作为高效的任务排队队列
broker = ListQueueBroker(
    url=REDIS_URL,
).with_result_backend(
    RedisAsyncResultBackend(redis_url=REDIS_URL)
)
