"""
OpenTelemetry 统一遥测初始化

职责：
1. 创建全局 TracerProvider（供 OTel FastAPI instrumentation 和 Langfuse 共用）
   并可选通过 OTLP 导出 traces
2. 创建 MeterProvider，通过 OTLP 将指标推送到 Prometheus
3. 自动 instrument FastAPI，替代原先的 prometheus-fastapi-instrumentator
"""

import logging
import os

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from backend.core.config import settings

logger = logging.getLogger(__name__)
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}

# OTel 资源标识 — service.name 在 Prometheus 中映射为 job 标签
_RESOURCE = Resource.create(
    {
        "service.name": "fastapi-backend",
        "service.version": settings.VERSION,
    }
)

# Prometheus v3+ 原生 OTLP receiver 端点
_PROMETHEUS_OTLP_ENDPOINT = os.getenv(
    "PROMETHEUS_OTLP_ENDPOINT",
    "http://prometheus:9090/api/v1/otlp",
)
_OTEL_TRACES_ENDPOINT = os.getenv(
    "OTEL_TRACES_ENDPOINT",
    "http://jaeger:4318/v1/traces",
)


def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY_ENV_VALUES


_ENABLE_OTEL_METRICS = _env_flag("ENABLE_OTEL_METRICS", "true")
_ENABLE_OTEL_TRACES = _env_flag("ENABLE_OTEL_TRACES", "false")


def setup_telemetry(app: FastAPI) -> None:
    """
    初始化 OpenTelemetry SDK 并 instrument FastAPI 应用。

    调用时机：在 app 创建之后、路由挂载之前。
    必须在 Langfuse SDK 初始化之前执行，确保 Langfuse 的 SpanProcessor
    注册到我们创建的 TracerProvider 上。
    """
    # ── 1. Traces ──────────────────────────────────────────────
    # 仅创建 TracerProvider 用于上下文传播和 Langfuse 集成。
    # Langfuse v3 SDK 会自动将其 SpanProcessor 注册到此 provider 上。
    # 在测试 / 本地环境中可选通过 OTLP 导出到 Jaeger。
    tracer_provider = TracerProvider(resource=_RESOURCE)
    if _ENABLE_OTEL_TRACES:
        span_exporter = OTLPSpanExporter(endpoint=_OTEL_TRACES_ENDPOINT)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # ── 2. Metrics ─────────────────────────────────────────────
    metric_readers = []
    if _ENABLE_OTEL_METRICS:
        # 通过 OTLP HTTP 推送指标到 Prometheus 的原生 OTLP receiver
        metric_exporter = OTLPMetricExporter(
            endpoint=_PROMETHEUS_OTLP_ENDPOINT,
        )
        metric_readers.append(
            PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=15_000,  # 与 Prometheus scrape_interval 对齐
            )
        )

    meter_provider = MeterProvider(
        resource=_RESOURCE,
        metric_readers=metric_readers,
    )
    metrics.set_meter_provider(meter_provider)

    # ── 3. Auto-instrument FastAPI ─────────────────────────────
    # 自动生成 http.server.request.duration 等 OTel 标准指标和 span
    FastAPIInstrumentor.instrument_app(app)

    logger.info(
        "OpenTelemetry 初始化完成: metrics=%s%s, traces=%s%s",
        "enabled" if _ENABLE_OTEL_METRICS else "disabled",
        f"→{_PROMETHEUS_OTLP_ENDPOINT}" if _ENABLE_OTEL_METRICS else "",
        "enabled" if _ENABLE_OTEL_TRACES else "disabled",
        f"→{_OTEL_TRACES_ENDPOINT}" if _ENABLE_OTEL_TRACES else "",
    )


def shutdown_telemetry() -> None:
    """在应用关闭时刷新并关闭 OTel providers，防止数据丢失。"""
    tracer_provider = trace.get_tracer_provider()
    tracer_shutdown = getattr(tracer_provider, "shutdown", None)
    if callable(tracer_shutdown):
        tracer_shutdown()

    meter_provider = metrics.get_meter_provider()
    meter_shutdown = getattr(meter_provider, "shutdown", None)
    if callable(meter_shutdown):
        meter_shutdown()

    logger.info("OpenTelemetry 已关闭")
