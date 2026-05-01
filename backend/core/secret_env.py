"""Docker secret environment loader.

职责：把受支持的 FOO_FILE 文件内容加载到对应 FOO 环境变量。
边界：只处理白名单中的 secret 名称，避免任意文件被写入环境。
副作用：模块导入时立即加载 secret，供 Settings 和第三方库读取。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SECRET_ENV_NAMES = {
    "SECRET_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "LLM_API_KEY",
    "RAG_EMBED_API_KEY",
    "LANGFUSE_SECRET_KEY",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
}


def load_secret_env() -> None:
    """加载受支持的 *_FILE secret 到环境变量。"""
    for name in SECRET_ENV_NAMES:
        path = os.getenv(f"{name}_FILE")
        if not path:
            continue

        try:
            value = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
        except FileNotFoundError:
            logger.warning("Secret file for %s does not exist: %s", name, path)
            continue
        except OSError:
            logger.exception("Failed to read secret file for %s: %s", name, path)
            continue

        os.environ[name] = value


load_secret_env()
