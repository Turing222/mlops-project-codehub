import os

import redis

# 从环境变量读取
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", 6379)
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# 建立连接池
pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,  # 关键点：带上密码
    decode_responses=True,
)
r = redis.Redis(connection_pool=pool)

# 测试缓存
r.set("test_key", "hello ai tutor", ex=3600)  # 设置 1 小时过期
