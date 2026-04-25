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
}


def load_secret_env() -> None:
    """Load supported FOO_FILE secrets into FOO for libraries that read env vars."""
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
