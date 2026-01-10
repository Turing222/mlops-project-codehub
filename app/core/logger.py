import logging
import sys
from pathlib import Path

# 定义日志格式：时间 - 名字 - 级别 - 消息
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def setup_logging():
    """
    通用日志配置
    """
    logger = logging.getLogger() # 获取根日志记录器
    logger.setLevel(logging.INFO)

    # 1. 输出到控制台的 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(console_handler)

    # 2. 如果需要，可以添加文件 Handler
    # log_file = Path("app.log")
    # file_handler = logging.FileHandler(log_file)
    # file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    # logger.addHandler(file_handler)

    # 降低一些第三方库冗余日志的级别
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

# 在 app/main.py 启动时调用此函数