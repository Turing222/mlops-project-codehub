import time
import uuid
from fastapi import HTTPException, Request, status
from backend.core.redis import redis_client

# Lua 脚本：实现滑动窗口算法
# KEYS[1]: 限流路径的 Key
# ARGV[1]: 当前时间戳 (毫秒)
# ARGV[2]: 窗口大小 (毫秒)
# ARGV[3]: 允许的最大请求数
LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

-- 1. 清理窗口外的数据
local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)

-- 2. 统计当前窗口内的请求数
local count = redis.call('ZCARD', key)

if count < limit then
    -- 3. 未超过限制，添加当前请求
    redis.call('ZADD', key, now, member)
    -- 4. 设置整个 ZSET 的过期时间（窗口时间转换为秒）
    redis.call('EXPIRE', key, math.ceil(window / 1000) + 1)
    return {1, count + 1}
else
    -- 5. 超过限制，返回 0 和当前计数值
    return {0, count}
end
"""

class RateLimiter:
    def __init__(self, times: int = 10, seconds: int = 60):
        self.times = times
        self.window_ms = seconds * 1000

    async def __call__(self, request: Request):
        # 1. 识别客户端 IP
        client_ip = request.headers.get("x-real-ip") or request.client.host
        key = f"rate_limit_sliding:{client_ip}:{request.url.path}"
        
        # 2. 获取 Redis 连接
        conn = await redis_client.init()
        
        # 3. 使用当前毫秒级时间戳和随机 member 保证唯一性
        now_ms = int(time.time() * 1000)
        request_id = str(uuid.uuid4())
        
        # 4. 执行 Lua 脚本 (返回 [status, count])
        # status 1 为成功, 0 为失败
        res = await conn.eval(
            LUA_SLIDING_WINDOW, 
            1, 
            key, 
            now_ms, 
            self.window_ms, 
            self.times,
            request_id
        )
        
        is_passed, current_count = res[0], res[1]
        
        if not is_passed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "访问太频繁了（动态窗口）",
                    "limit_count": self.times,
                    "current_count": current_count
                }
            )
