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
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_inflight = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """请求调用许可；熔断打开时直接抛异常。"""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.cooldown_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_inflight = 0
                    logger.info(
                        "Circuit breaker entered half-open state; probing recovery",
                        extra={
                            "event": "circuit_breaker_half_open",
                            "service": self.name,
                            "circuit_state": CircuitState.HALF_OPEN.value,
                        },
                    )
                    # 落入下方半开准入逻辑，按名额放行探测请求
                else:
                    raise app_service_error(
                        f"服务 {self.name} 暂时不可用，已熔断保护",
                        code="CIRCUIT_BREAKER_OPEN",
                        details={
                            "service": self.name,
                            "failure_count": self._failure_count,
                        },
                    )
            # HALF_OPEN: 仅放行 half_open_max_calls 个并发探测，其余快速失败，
            # 避免恢复瞬间积压请求一齐涌向尚在恢复的下游。
            if self._half_open_inflight < self.half_open_max_calls:
                self._half_open_inflight += 1
                return
            raise app_service_error(
                f"服务 {self.name} 正在探测恢复，暂不接受新请求",
                code="CIRCUIT_BREAKER_OPEN",
                details={
                    "service": self.name,
                    "failure_count": self._failure_count,
                },
            )

    async def on_success(self) -> None:
        """调用成功时记录，关闭断路器。"""
        async with self._lock:
            # 过期探测：半开期间另一路探测已失败并将状态打回 OPEN 时，
            # 忽略晚到的成功回调，避免误闭合。
            if self._state == CircuitState.OPEN:
                return
            if self._state == CircuitState.HALF_OPEN:
                logger.info(
                    "Circuit breaker recovered and closed after a successful probe",
                    extra={
                        "event": "circuit_breaker_recovered",
                        "service": self.name,
                        "circuit_state": CircuitState.CLOSED.value,
                    },
                )
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_inflight = 0

    async def on_failure(self) -> None:
        """调用失败时记录，超标时打开断路器。"""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._half_open_inflight = 0
                logger.warning(
                    "Circuit breaker reopened after a failed half-open probe",
                    extra={
                        "event": "circuit_breaker_reopened",
                        "service": self.name,
                        "failure_count": self._failure_count,
                        "circuit_state": CircuitState.OPEN.value,
                    },
                )
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker opened after reaching the failure threshold",
                    extra={
                        "event": "circuit_breaker_opened",
                        "service": self.name,
                        "failure_count": self._failure_count,
                        "failure_threshold": self.failure_threshold,
                        "circuit_state": CircuitState.OPEN.value,
                    },
                )
