"""Langfuse tracing helpers.

职责：封装 Langfuse trace metadata 绑定和 generation span 创建；
     应用启动时显式初始化 Langfuse 客户端并安装 span 过滤器。
边界：本模块知道 Langfuse SDK，也知道它借 OTel context propagation 工作；trace_utils.py 不知道 Langfuse 存在。
失败处理：无参数时 no-op；有参数时懒导入 langfuse，先 get_client() 确保 SDK 初始化。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


@contextmanager
def set_langfuse_trace_metadata(
    *,
    user_id: Any | None = None,
    session_id: Any | None = None,
    tags: Sequence[str] | None = None,
) -> Iterator[None]:
    """绑定 Langfuse trace 级属性 (user_id / session_id / tags) 到当前 OTel context。

    无参数时 no-op；有参数时懒导入 langfuse，先 get_client() 确保 SDK 初始化，
    再进入 propagate_attributes(...) 使所有子 span 继承这些属性。
    """
    if user_id is None and session_id is None and not tags:
        yield
        return

    from langfuse import get_client, propagate_attributes

    get_client()
    with propagate_attributes(
        user_id=str(user_id) if user_id else None,
        session_id=str(session_id) if session_id else None,
        tags=list(tags) if tags else None,
    ):
        yield


class _LangfuseGenerationRecorder:
    """Langfuse generation 后置更新包装器。

    调用方通过 record() 延迟写入 output / usage / metadata / model / error，
    上下文退出时 Langfuse SDK 自动调用 generation.end()。
    """

    __slots__ = ("_generation",)

    def __init__(self, generation: Any) -> None:
        self._generation = generation

    def record(
        self,
        *,
        output: Any | None = None,
        usage: dict[str, int] | None = None,
        metadata: Any | None = None,
        model: str | None = None,
        error: str | None = None,
    ) -> None:
        update_kwargs: dict[str, Any] = {}
        if output is not None:
            update_kwargs["output"] = output
        if usage is not None:
            update_kwargs["usage_details"] = usage
        if metadata is not None:
            update_kwargs["metadata"] = metadata
        if model is not None:
            update_kwargs["model"] = model
        if error is not None:
            update_kwargs["status_message"] = error
            update_kwargs["level"] = "ERROR"
        if update_kwargs:
            self._generation.update(**update_kwargs)


@contextmanager
def langfuse_generation(
    *,
    name: str,
    input_payload: Any | None = None,
    model: str | None = None,
    metadata: Any | None = None,
) -> Iterator[_LangfuseGenerationRecorder]:
    """创建 Langfuse generation observation，返回 recorder 供后置更新。

    正常退出时 Langfuse SDK 自动调用 generation.end()；
    异常时 recorder 自动记录 error 后重新抛出。
    """
    from langfuse import get_client

    create_kwargs: dict[str, Any] = {"name": name}
    if input_payload is not None:
        create_kwargs["input"] = input_payload
    if model is not None:
        create_kwargs["model"] = model
    if metadata is not None:
        create_kwargs["metadata"] = metadata

    with get_client().start_as_current_generation(**create_kwargs) as generation:
        recorder = _LangfuseGenerationRecorder(generation)
        try:
            yield recorder
        except Exception as exc:
            recorder.record(error=str(exc))
            raise


# ---------------------------------------------------------------------------
# Langfuse client initialization & span filter installation
# ---------------------------------------------------------------------------

_langfuse_filter_installed = False


def init_langfuse_client() -> None:
    """显式初始化 Langfuse 客户端，并安装 FilteringSpanProcessor。

    做两件事：
    1. 构造 ``Langfuse()`` 实例并传入 ``blocked_instrumentation_scopes``，
       阻挡 FastAPI / SQLAlchemy 自动埋点的 span 进入 Langfuse。
    2. 在 Langfuse SDK 内部附加 LangfuseSpanProcessor 之后，
       用 ``FilteringSpanProcessor`` 包裹它，按 span name 白名单过滤
       ``backend.business`` tracer 下非 LLM 的 span（如 http.rate_limit）。

    必须在 ``setup_telemetry()`` 末尾调用（TracerProvider 已创建、
    Langfuse SDK 能找到它并附加 SpanProcessor）。

    幂等：重复调用无副作用。
    """
    global _langfuse_filter_installed
    if _langfuse_filter_installed:
        return

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    # -- Step 1: 显式构造 Langfuse 客户端，传入 blocked_instrumentation_scopes ----
    # SDK 的 get_client() 会复用已存在的实例，所以后续调用 get_client()
    # 不再重复构造，blocked_instrumentation_scopes 配置生效。
    try:
        from langfuse import Langfuse

        Langfuse(
            blocked_instrumentation_scopes=[
                "opentelemetry.instrumentation.fastapi",
                "opentelemetry.instrumentation.sqlalchemy",
            ],
        )
    except Exception:
        logger.warning(
            "Langfuse 客户端初始化失败（可能缺少 LANGFUSE_PUBLIC_KEY 等环境变量），"
            "跳过 span 过滤器安装",
            exc_info=True,
        )
        return

    # -- Step 2: 后置包裹 LangfuseSpanProcessor ----------------------------------
    from langfuse._client.span_processor import LangfuseSpanProcessor

    from backend.observability.filtering_span_processor import (
        FilteringSpanProcessor,
        should_export_to_langfuse,
    )

    tracer_provider = trace.get_tracer_provider()
    if not isinstance(tracer_provider, TracerProvider):
        logger.debug("TracerProvider 不是 SDK 实例，跳过 span 过滤器安装")
        _langfuse_filter_installed = True
        return

    multi = tracer_provider._active_span_processor
    processors = list(multi._span_processors)

    for i, proc in enumerate(processors):
        if isinstance(proc, LangfuseSpanProcessor):
            filtered = FilteringSpanProcessor(
                proc,
                allow_fn=should_export_to_langfuse,
            )
            processors[i] = filtered
            break
    else:
        logger.debug("未找到 LangfuseSpanProcessor，跳过过滤器安装")
        _langfuse_filter_installed = True
        return

    with multi._lock:
        multi._span_processors = tuple(processors)

    _langfuse_filter_installed = True
    logger.info("Langfuse span 过滤器已安装：仅导出 LLM 相关 span")
