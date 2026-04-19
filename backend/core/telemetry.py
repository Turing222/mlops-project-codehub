"""
OpenTelemetry 统一遥测初始化

职责：
1. 创建全局 TracerProvider（供 OTel FastAPI instrumentation 和 Langfuse 共用）
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
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from backend.core.config import settings

logger = logging.getLogger(__name__)

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
    # 如果后续需要 Jaeger / Tempo，在此添加 BatchSpanProcessor。
    tracer_provider = TracerProvider(resource=_RESOURCE)
    trace.set_tracer_provider(tracer_provider)

    # ── 2. Metrics ─────────────────────────────────────────────
    # 通过 OTLP HTTP 推送指标到 Prometheus 的原生 OTLP receiver
    metric_exporter = OTLPMetricExporter(
        endpoint=_PROMETHEUS_OTLP_ENDPOINT,
    )
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=15_000,  # 与 Prometheus scrape_interval 对齐
    )
    meter_provider = MeterProvider(
        resource=_RESOURCE,
        metric_readers=[metric_reader],
    )
    metrics.set_meter_provider(meter_provider)

    # ── 3. Auto-instrument FastAPI ─────────────────────────────
    # 自动生成 http.server.request.duration 等 OTel 标准指标和 span
    FastAPIInstrumentor.instrument_app(app)

    logger.info(
        "OpenTelemetry 初始化完成: metrics→%s, traces→TracerProvider ready",
        _PROMETHEUS_OTLP_ENDPOINT,
    )


def shutdown_telemetry() -> None:
    """在应用关闭时刷新并关闭 OTel providers，防止数据丢失。"""
    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "shutdown"):
        tracer_provider.shutdown()

    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
        meter_provider.shutdown()

    logger.info("OpenTelemetry 已关闭")
