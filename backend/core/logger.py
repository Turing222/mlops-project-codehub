"""JSON logging setup.

职责：配置根 logger 的 JSON 输出，并注入常用字段与 OTel trace 上下文。
边界：本模块不决定业务日志内容；调用方仍负责选择日志级别和字段。
副作用：setup_logging 会清理根 logger 现有 handler，避免重复输出。
"""

import datetime
import logging
import sys
from typing import Any

import orjson
from pythonjsonlogger import jsonlogger

try:
    from opentelemetry import trace as otel_trace

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


class OrjsonFormatter(jsonlogger.JsonFormatter):
    """使用 orjson 序列化并补齐标准字段的 JSON formatter。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # 保留业务 extra 字段，过滤掉 logging.LogRecord 的内部噪声。
        if "reserved_attrs" not in kwargs:
            kwargs["reserved_attrs"] = (
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "taskName",
            )
        super().__init__(*args, **kwargs)

    def json_serializer(self, obj: object) -> str:
        """返回 python-json-logger 需要的 JSON 字符串。"""
        return orjson.dumps(obj).decode("utf-8")

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        # timestamp 字段名固定，方便日志检索和仪表盘复用。
        if log_record.get("asctime"):
            log_record["timestamp"] = log_record.pop("asctime")
        else:
            log_record["timestamp"] = datetime.datetime.fromtimestamp(
                record.created
            ).isoformat()

        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["module"] = record.module
        log_record["func_name"] = record.funcName
        log_record["line_no"] = record.lineno

        # trace_id/span_id 直接进入日志，便于从日志跳转到 trace。
        if _OTEL_AVAILABLE:
            span = otel_trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.trace_id:
                log_record["trace_id"] = f"{ctx.trace_id:032x}"
                log_record["span_id"] = f"{ctx.span_id:016x}"


def setup_logging() -> None:
    """配置根 logger 的控制台 JSON 输出。"""

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    json_formatter = OrjsonFormatter()

    # 多次初始化时先清空 handler，避免同一日志被重复发送。
    if logger.handlers:
        logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(json_formatter)
    logger.addHandler(console_handler)

    # 第三方访问/SQL 日志量大，默认降级以保留业务日志信噪比。
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
