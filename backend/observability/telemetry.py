"""OpenTelemetry setup.

职责：初始化全局 TracerProvider、MeterProvider，并 instrument FastAPI。
边界：本模块不创建业务 span；业务 span 由 trace_utils 和调用方负责。
副作用：调用 setup_telemetry 会设置进程全局 OTel provider。
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

from backend.config.settings import settings

logger = logging.getLogger(__name__)
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}

# service.name 会成为 Prometheus/trace 后端中的服务标识。
_RESOURCE = Resource.create(
    {
        "service.name": "fastapi-backend",
        "service.version": settings.VERSION,
    }
)

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
    """初始化 OTel provider，并在路由挂载前 instrument FastAPI。"""
    # 先创建 TracerProvider，Langfuse SDK 才能把 SpanProcessor 挂到同一 provider。
    tracer_provider = TracerProvider(resource=_RESOURCE)
    if _ENABLE_OTEL_TRACES:
        span_exporter = OTLPSpanExporter(endpoint=_OTEL_TRACES_ENDPOINT)
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_readers = []
    if _ENABLE_OTEL_METRICS:
        metric_exporter = OTLPMetricExporter(
            endpoint=_PROMETHEUS_OTLP_ENDPOINT,
        )
        metric_readers.append(
            PeriodicExportingMetricReader(
                metric_exporter,
                export_interval_millis=15_000,
            )
        )

    meter_provider = MeterProvider(
        resource=_RESOURCE,
        metric_readers=metric_readers,
    )
    metrics.set_meter_provider(meter_provider)

    # 自动生成 http.server.request.duration 等 OTel 标准指标和 span。
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
