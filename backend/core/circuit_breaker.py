"""Circuit breaker for external service calls.

职责：监视外部服务调用的连续失败次数，超阈值时快速失败避免雪崩。
边界：状态是进程内的，不跨 worker 协调。
"""

import asyncio
import logging
import time
from enum import Enum

from backend.core.exceptions import app_service_error

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """跟踪连续失败并按阈值熔断。"""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: int = 30,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """请求调用许可；熔断打开时直接抛异常。"""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.cooldown_seconds:
                    self._state = CircuitState.HALF_OPEN
                    logger.info(
                        "断路器进入半开状态(name=%s)，尝试探测恢复",
                        self.name,
                    )
                    return  # 半开状态允许请求通过以探测恢复
                raise app_service_error(
                    f"服务 {self.name} 暂时不可用，已熔断保护",
                    code="CIRCUIT_BREAKER_OPEN",
                    details={
                        "service": self.name,
                        "failure_count": self._failure_count,
                    },
                )
            # HALF_OPEN: 允许通过，探测恢复
            return

    async def on_success(self) -> None:
        """调用成功时记录，关闭断路器。"""
        async with self._lock:
            if self._state != CircuitState.CLOSED:
                logger.info(
                    "断路器恢复(name=%s): 探测成功，关闭断路器",
                    self.name,
                )
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    async def on_failure(self) -> None:
        """调用失败时记录，超标时打开断路器。"""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "断路器重新打开(name=%s): 半开探测失败",
                    self.name,
                )
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    "断路器打开(name=%s): 连续失败 %d 次",
                    self.name,
                    self._failure_count,
                )
