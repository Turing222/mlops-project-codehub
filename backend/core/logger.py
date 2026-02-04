import datetime
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from backend.core.config import settings


# --- 1. 自定义 JSON 格式化器 ---
class JSONFormatter(logging.Formatter):
    """
    将日志输出为 JSON 格式，方便机器解析
    """

    def format(self, record):
        # 提取日志记录中的基本信息
        log_record = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created
            ).isoformat(),  # ISO8601 时间格式
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "func_name": record.funcName,
            "line_no": record.lineno,
        }

        # 如果有异常堆栈信息，也加入到 JSON 中
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        # 转换为 JSON 字符串，ensure_ascii=False 保证中文正常显示
        return json.dumps(log_record, ensure_ascii=False)


def setup_logging():
    """
    通用日志配置
    """
    # 确保日志文件夹存在（无论从哪启动，路径都由 settings 决定）
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_dir = settings.LOG_DIR

    logger = logging.getLogger()  # 获取根日志记录器
    # logger.setLevel(logging.INFO)
    logger.setLevel(logging.DEBUG)
    # 创建通用的 JSON Formatter 实例化
    json_formatter = JSONFormatter()

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


# 在 app/main.py 启动时调用此函数
