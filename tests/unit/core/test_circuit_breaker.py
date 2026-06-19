"""Circuit breaker state-machine unit tests.

职责：直接验证 CircuitBreaker 状态机全路径（CLOSED/OPEN/HALF_OPEN 转换、阈值触发、
冷却放行、半开探测限流），作为熔断改造的回归基线；边界：纯进程内对象，不接入 LLM
service，cooldown=0 控制时间，不依赖真实时钟等待；副作用：无。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.circuit_breaker import CircuitBreaker, CircuitState
from backend.core.exceptions import AppException


def make_breaker(
    *,
    failure_threshold: int = 3,
    cooldown_seconds: int = 0,
    half_open_max_calls: int = 1,
) -> CircuitBreaker:
    return CircuitBreaker(
        name="test",
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
        half_open_max_calls=half_open_max_calls,
    )

async def open_breaker(breaker: CircuitBreaker) -> None:
    """连续失败到阈值，把断路器打到 OPEN。"""
    for _ in range(breaker.failure_threshold):
        await breaker.on_failure()

async def assert_circuit_open(breaker: CircuitBreaker) -> None:
    with pytest.raises(AppException) as exc_info:
        await breaker.acquire()
    assert exc_info.value.code == "CIRCUIT_BREAKER_OPEN"

# CLOSED

async def test_closed_breaker_allows_calls() -> None:
    breaker = make_breaker()

    await breaker.acquire()  # 不抛异常即通过

    assert breaker._state == CircuitState.CLOSED

async def test_failures_below_threshold_stay_closed() -> None:
    breaker = make_breaker(failure_threshold=3)

    await breaker.on_failure()
    await breaker.on_failure()

    assert breaker._state == CircuitState.CLOSED
    await breaker.acquire()

# CLOSED -> OPEN
async def test_reaching_threshold_opens_circuit() -> None:
    breaker = make_breaker(failure_threshold=3, cooldown_seconds=60)

    await open_breaker(breaker)

    assert breaker._state == CircuitState.OPEN
    # 冷却未到，OPEN 期间快速失败
    await assert_circuit_open(breaker)

# OPEN -> HALF_OPEN
async def test_cooldown_elapsed_transitions_to_half_open() -> None:
    breaker = make_breaker(failure_threshold=3, cooldown_seconds=0)

    await open_breaker(breaker)
    await breaker.acquire()  # cooldown=0，立即转半开并放行探测

    assert breaker._state == CircuitState.HALF_OPEN

# HALF_OPEN -> CLOSED / OPEN
async def test_half_open_success_closes_circuit() -> None:
    breaker = make_breaker(failure_threshold=3, cooldown_seconds=0)

    await open_breaker(breaker)
    await breaker.acquire()  # -> HALF_OPEN
    await breaker.on_success()

    assert breaker._state == CircuitState.CLOSED
    assert breaker._failure_count == 0
    await breaker.acquire()  # 已恢复，正常放行

async def test_half_open_failure_reopens_circuit() -> None:
    breaker = make_breaker(failure_threshold=3, cooldown_seconds=0)

    await open_breaker(breaker)
    await breaker.acquire()  # cooldown=0 -> HALF_OPEN
    await breaker.on_failure()  # 探测失败 -> 立即重开

    assert breaker._state == CircuitState.OPEN

# HALF_OPEN 探测限流（缺陷 1 的目标行为）
async def test_half_open_limits_concurrent_probes() -> None:
    breaker = make_breaker(failure_threshold=3, cooldown_seconds=0)

    await open_breaker(breaker)
    await breaker.acquire()  # 第一个探测放行 -> HALF_OPEN, inflight=1

    # 探测尚未返回（未 on_success/on_failure），半开名额已满，后续请求快速失败
    await assert_circuit_open(breaker)
    assert breaker._state == CircuitState.HALF_OPEN

async def test_half_open_max_calls_allows_configured_probes() -> None:
    breaker = make_breaker(
        failure_threshold=3, cooldown_seconds=0, half_open_max_calls=2
    )

    await open_breaker(breaker)
    await breaker.acquire()  # 探测 1
    await breaker.acquire()  # 探测 2（名额=2，仍放行）

    await assert_circuit_open(breaker)  # 探测 3 超额，快速失败

async def test_half_open_inflight_resets_after_resolution() -> None:
    breaker = make_breaker(failure_threshold=3, cooldown_seconds=0)

    await open_breaker(breaker)
    await breaker.acquire()  # -> HALF_OPEN, inflight=1
    await breaker.on_failure()  # 探测失败 -> OPEN, inflight 复位

    # 再次进入半开时名额应已释放，可以放行新探测
    await breaker.acquire()
    assert breaker._state == CircuitState.HALF_OPEN
    assert breaker._half_open_inflight == 1

async def test_half_open_concurrent_acquire_limits_probes() -> None:
    breaker = make_breaker(failure_threshold=3, cooldown_seconds=0)

    await open_breaker(breaker)

    outcomes = await asyncio.gather(
        breaker.acquire(),
        breaker.acquire(),
        return_exceptions=True,
    )

    assert sum(isinstance(outcome, AppException) for outcome in outcomes) == 1
    assert breaker._state == CircuitState.HALF_OPEN
    assert breaker._half_open_inflight == 1

async def test_stale_half_open_success_ignored_after_reopen() -> None:
    breaker = make_breaker(
        failure_threshold=3, cooldown_seconds=0, half_open_max_calls=2
    )

    await open_breaker(breaker)
    await breaker.acquire()
    await breaker.acquire()
    await breaker.on_failure()  # 一路探测失败 -> OPEN

    assert breaker._state == CircuitState.OPEN

    await breaker.on_success()  # 晚到的成功不应闭合

    assert breaker._state == CircuitState.OPEN
