import functools
import json
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# 假设你的日志工具已经配置好可以自动抓取 contextvars 中的 request_id
logger = logging.getLogger("app.decorators")


class NamedCallable(Protocol):
    """Protocol for callables that have a __name__ attribute."""

    __name__: str

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


def monitor_action(
    *,
    name: str | None = None,
    log_args: bool = False,
):
    """
    异步 耗时统计装饰器。

    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            action = name or func.__name__
            start = time.time()
            try:
                if log_args:
                    logger.debug(f"[TX-ARGS] {action} args={args} kwargs={kwargs}")
                # 纯粹执行逻辑，不再干涉 session.commit()
                result = await func(*args, **kwargs)

                cost = (time.time() - start) * 1000
                logger.info(f"[DONE] {action} | cost: {cost:.2f}ms")
                return result
            except Exception as e:
                cost = (time.time() - start) * 1000
                # 只负责记录异常日志，不负责 rollback
                logger.error(f"[FAIL] {action} | cost: {cost:.2f}ms | error: {str(e)}")
                raise  # 抛出异常，交给外层的 session.begin() 去处理回滚

        return wrapper

    return decorator


def log_performance(func: NamedCallable):
    """
    耗时统计装饰器
    用于指标监控：记录函数执行时间，并关联 Request ID
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            duration = time.perf_counter() - start_time
            # 这里记录的日志会自动带上中间件注入的 request_id
            logger.info(f"Function {func.__name__} executed in {duration:.4f}s")
            return result
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                f"Function {func.__name__} failed after {duration:.4f}s with error: {e}"
            )
            raise e

    return wrapper


def retry_on_failure(
    attempts: int = 3,
    min_wait: int = 2,
    max_wait: int = 10,
    catch_exceptions: tuple = (Exception,),
):
    """
    重试装饰器
    使用指数退避算法，防止在高并发 Socket 冲击下直接把下游压死
    """
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(catch_exceptions),
        reraise=True,
        # 这里的 before 钩子可以让你在日志里看到“第几次重试”
        before=lambda retry_state: logger.warning(
            f"Retrying {retry_state.fn.__name__}: attempt #{retry_state.attempt_number}"
        ),
    )


def cache_result(redis_client, prefix: str, expire: int = 3600):
    """
    Redis 缓存装饰器
    DBA 视角：$O(1)$ 查询，减少数据库 IO 压力
    """

    def decorator(func: NamedCallable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 简单的 Key 生成逻辑：prefix + 函数名 + 参数哈希
            # 注意：实际生产中需要更严谨的 key 处理逻辑
            cache_key = f"{prefix}:{func.__name__}:{hash(str(args) + str(kwargs))}"

            # 1. 尝试从 Redis 获取
            cached_val = await redis_client.get(cache_key)
            if cached_val:
                logger.debug(f"Cache hit for {cache_key}")
                return json.loads(cached_val)

            # 2. 穿透：执行原函数
            result = await func(*args, **kwargs)

            # 3. 回填 Redis
            if result:
                await redis_client.set(cache_key, json.dumps(result), ex=expire)
            return result

        return wrapper

    return decorator
