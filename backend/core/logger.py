import datetime
import logging
import sys
import orjson
from pythonjsonlogger import jsonlogger

from backend.core.config import settings

class OrjsonFormatter(jsonlogger.JsonFormatter):
    """
    使用 orjson 高性能序列化的 JSON 格式化器
    """
    def __init__(self, *args, **kwargs):
        # 预设常用的日志字段
        if "reserved_attrs" not in kwargs:
            kwargs["reserved_attrs"] = (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module",
                "msecs", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName"
            )
        super(OrjsonFormatter, self).__init__(*args, **kwargs)

    def json_serializer(self, obj):
        # 使用 orjson 序列化，并返回字符串
        # option=orjson.OPT_PASSTHROUGH_DATETIME 用于处理时间，
        # 但 JsonFormatter 默认会把时间转存为 asctime 字符串
        return orjson.dumps(obj).decode("utf-8")

    def add_fields(self, log_record, record, message_dict):
        super(OrjsonFormatter, self).add_fields(log_record, record, message_dict)
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
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    """
    # --- 2. 配置 INFO 级别日志 (记录所有日常流水) ---
    # 文件名：logs/application.log
    # 策略：每天午夜切割，保留30天
    info_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_dir / "application.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)  # 包含 INFO, WARNING, ERROR
    info_handler.setFormatter(json_formatter)
    logger.addHandler(info_handler)

    # --- 3. 配置 ERROR 级别日志 (只记录报错) ---
    # 文件名：logs/error.log
    # 策略：每天午夜切割，保留30天
    # 作用：运维告警只监控这个文件，干扰少
    error_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_dir / "error.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)  # 只包含 ERROR, CRITICAL
    error_handler.setFormatter(json_formatter)
    logger.addHandler(error_handler)

    # 降低一些第三方库冗余日志的级别
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    """
