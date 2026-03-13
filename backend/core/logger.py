import datetime
import logging
import sys

import orjson
from pythonjsonlogger import jsonlogger


class OrjsonFormatter(jsonlogger.JsonFormatter):
    """
    使用 orjson 高性能序列化的 JSON 格式化器
    """

    def __init__(self, *args, **kwargs):
        # 预设常用的日志字段
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

    def json_serializer(self, obj):
        # 使用 orjson 序列化，并返回字符串
        # option=orjson.OPT_PASSTHROUGH_DATETIME 用于处理时间，
        # 但 JsonFormatter 默认会把时间转存为 asctime 字符串
        return orjson.dumps(obj).decode("utf-8")

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        # 统一时间字段名为 timestamp
        if log_record.get("asctime"):
            log_record["timestamp"] = log_record.pop("asctime")
        else:
            log_record["timestamp"] = datetime.datetime.fromtimestamp(
                record.created
            ).isoformat()

        # 丰富字段信息
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["module"] = record.module
        log_record["func_name"] = record.funcName
        log_record["line_no"] = record.lineno


def setup_logging():
    """
    通用日志配置
    """
    # 确保日志文件夹存在（无论从哪启动，路径都由 settings 决定）
    # settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    # log_dir = settings.LOG_DIR

    logger = logging.getLogger()  # 获取根日志记录器
    # logger.setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)
    # 创建通用的 JSON Formatter 实例化
    json_formatter = OrjsonFormatter()

    # 清除已有的 Handler（防止多次调用导致重复打印）
    if logger.handlers:
        logger.handlers.clear()

    # 1. 输出到控制台的 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    # 使用预先配置好的 JSON Formatter
    console_handler.setFormatter(json_formatter)
    logger.addHandler(console_handler)

    # 降低一些第三方库冗余日志的级别，防止刷屏
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
