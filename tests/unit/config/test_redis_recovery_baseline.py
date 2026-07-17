"""Redis recovery deployment baseline tests.

职责：锁定 T1-4 前缓存与任务 Redis 共用、可淘汰且无持久卷的部署基线；
边界：只读取仓库 Compose 配置并构造 Settings，不启动 Docker 或 Redis；副作用：无。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml

from backend.config.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = PROJECT_ROOT / "deploy" / "docker-compose.yml"


def test_current_compose_shares_one_evictable_nonpersistent_redis() -> None:
    """WS2 baseline: cache, broker, and result traffic share one Redis service."""
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = compose["services"]
    redis_services = {
        name: service
        for name, service in services.items()
        if str(service.get("image", "")).startswith("redis:")
    }

    assert set(redis_services) == {"redis"}
    redis_service = redis_services["redis"]
    command = redis_service["command"]
    assert "maxmemory-policy allkeys-lru" in command
    assert "appendonly yes" not in command
    assert "volumes" not in redis_service
    for service_name in ("api", "task_worker", "credit_scheduler"):
        assert "redis" in services[service_name]["depends_on"]


def test_current_taskiq_url_fallback_reuses_cache_redis_endpoint() -> None:
    """WS2 baseline: DB selection separates keys but not the Redis failure domain."""
    settings = Settings(
        _env_file=None,
        APP_ENV="local",
        REDIS_URL="redis://:secret@redis:6379/0",
        TASKIQ_REDIS_URL=None,
    )

    cache_url = urlsplit(settings.redis_url)
    task_url = urlsplit(settings.taskiq_redis_url)
    assert (task_url.hostname, task_url.port) == (cache_url.hostname, cache_url.port)
    assert cache_url.path == "/0"
    assert task_url.path == "/1"
