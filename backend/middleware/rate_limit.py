import ipaddress
import time
import uuid

from fastapi import Request

from backend.core.config import settings
from backend.core.exceptions import app_too_many_requests
from backend.core.redis import redis_client
from backend.core.trace_utils import (
    set_current_span_attributes,
    set_span_attributes,
    trace_span,
)

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
    def __init__(
        self,
        times: int = 10,
        seconds: int = 60,
        trusted_proxy_cidrs: str | None = None,
    ):
        self.times = times
        self.window_ms = seconds * 1000
        raw_cidrs = (
            trusted_proxy_cidrs
            if trusted_proxy_cidrs is not None
            else settings.RATE_LIMIT_TRUSTED_PROXY_CIDRS
        )
        self.trusted_proxy_networks = self._parse_cidr_list(raw_cidrs)

    async def __call__(self, request: Request):
        # 1. 识别客户端 IP（仅当来源是可信代理时才信任代理头）
        client_ip = self._get_client_ip(request)
        path = request.url.path
        key = f"rate_limit_sliding:{client_ip}:{path}"
        trace_attrs = {
            "rate_limit.algorithm": "redis_sliding_window",
            "rate_limit.limit": self.times,
            "rate_limit.window_ms": self.window_ms,
            "rate_limit.client_ip": client_ip,
            "http.target": path,
        }

        with trace_span("http.rate_limit", trace_attrs) as span:
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
                request_id,
            )

            is_passed = bool(res[0])
            current_count = int(res[1])
            result_attrs = {
                "rate_limit.allowed": is_passed,
                "rate_limit.current_count": current_count,
            }
            request.state.rate_limit = result_attrs
            set_span_attributes(span, result_attrs)
            set_current_span_attributes(result_attrs)

            if not is_passed:
                raise app_too_many_requests(
                    "访问太频繁了（动态窗口）",
                    details={
                        "limit_count": self.times,
                        "current_count": current_count,
                    },
                )

    def _get_client_ip(self, request: Request) -> str:
        peer_ip = request.client.host if request.client else ""
        if peer_ip and self._is_trusted_proxy(peer_ip):
            real_ip = request.headers.get("x-real-ip", "").strip()
            if self._is_valid_ip(real_ip):
                return real_ip
        return peer_ip or "unknown"

    def _is_trusted_proxy(self, peer_ip: str) -> bool:
        if not self.trusted_proxy_networks:
            return False
        try:
            ip_obj = ipaddress.ip_address(peer_ip)
        except ValueError:
            return False
        return any(ip_obj in network for network in self.trusted_proxy_networks)

    @staticmethod
    def _is_valid_ip(value: str) -> bool:
        if not value:
            return False
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def _parse_cidr_list(
        raw_cidrs: str,
    ) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        cidr_items = [item.strip() for item in raw_cidrs.split(",") if item.strip()]
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for item in cidr_items:
            network = ipaddress.ip_network(item, strict=False)
            networks.append(network)
        return networks
