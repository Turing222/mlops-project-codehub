from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from backend.core.config import settings

# TaskIQ 优先使用 TASKIQ_REDIS_URL，未配置时回落到 REDIS_URL 的 DB1 变体
REDIS_URL = settings.taskiq_redis_url

# 使用 Redis 的 List 结构作为高效的任务排队队列
broker = ListQueueBroker(
    url=REDIS_URL,
).with_result_backend(
    RedisAsyncResultBackend(redis_url=REDIS_URL)
)
