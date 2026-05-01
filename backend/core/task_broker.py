"""TaskIQ broker configuration.

职责：创建 Redis-backed TaskIQ broker 和结果后端。
边界：本模块只配置队列连接，不定义任务业务逻辑。
副作用：导入后会创建 broker 对象，供任务装饰器注册使用。
"""

from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from backend.core.config import settings

# TaskIQ 使用独立 Redis DB，避免业务缓存和队列 key 混在一起。
REDIS_URL = settings.taskiq_redis_url

broker = ListQueueBroker(
    url=REDIS_URL,
).with_result_backend(
    RedisAsyncResultBackend(redis_url=REDIS_URL)
)
