"""Redis responsibility isolation deployment contract tests.

职责：锁定缓存 Redis 与 TaskIQ broker/result Redis 的独立故障域及持久化基线；
边界：只读取仓库 Compose 配置并构造 Settings，不启动 Docker 或 Redis；副作用：无。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml

from backend.config.settings import Settings
from backend.config.settings import settings as app_settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_COMPOSE_FILE = PROJECT_ROOT / "deploy" / "docker-compose.yml"
SMOKE_COMPOSE_FILE = PROJECT_ROOT / "docker-compose.db.yml"
K8S_CONFIGMAP_FILE = PROJECT_ROOT / "deploy" / "k8s" / "configmap.yaml"
K8S_KEDA_FILE = PROJECT_ROOT / "deploy" / "k8s" / "worker-keda-scaledobject.yaml"


def _assert_isolated_redis_services(compose_file: Path) -> None:
    compose = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    services = compose["services"]
    redis_services = {
        name: service
        for name, service in services.items()
        if str(service.get("image", "")).startswith("redis:")
    }

    assert set(redis_services) == {"redis-cache", "redis-taskiq"}

    cache = redis_services["redis-cache"]
    cache_command = cache["command"]
    assert "maxmemory-policy allkeys-lru" in cache_command
    assert "appendonly yes" not in cache_command
    assert "volumes" not in cache

    taskiq = redis_services["redis-taskiq"]
    taskiq_command = taskiq["command"]
    assert "maxmemory-policy noeviction" in taskiq_command
    assert "appendonly yes" in taskiq_command
    assert "appendfsync everysec" in taskiq_command
    assert any(str(volume).endswith(":/data") for volume in taskiq["volumes"])
    assert "healthcheck" in taskiq

    for service_name in ("api", "task_worker"):
        assert "redis-cache" in services[service_name]["depends_on"]
        assert "redis-taskiq" in services[service_name]["depends_on"]
    if "credit_scheduler" in services:
        assert "redis-taskiq" in services["credit_scheduler"]["depends_on"]


def test_production_compose_isolates_cache_and_task_redis() -> None:
    _assert_isolated_redis_services(PRODUCTION_COMPOSE_FILE)


def test_smoke_compose_isolates_cache_and_task_redis() -> None:
    _assert_isolated_redis_services(SMOKE_COMPOSE_FILE)


def test_taskiq_url_default_uses_a_distinct_redis_endpoint() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="local",
        REDIS_URL="redis://:secret@redis-cache:6379/0",
        TASKIQ_REDIS_URL=None,
        TASKIQ_REDIS_HOST="redis-taskiq",
        TASKIQ_REDIS_PORT=6379,
        REDIS_PASSWORD="secret",
    )

    cache_url = urlsplit(settings.redis_url)
    task_url = urlsplit(settings.taskiq_redis_url)
    assert (task_url.hostname, task_url.port) != (cache_url.hostname, cache_url.port)
    assert (task_url.hostname, task_url.port) == ("redis-taskiq", 6379)
    assert cache_url.path == "/0"
    assert task_url.path == "/0"


def test_taskiq_result_backend_has_an_explicit_ttl() -> None:
    from backend.infra.task_broker import broker

    assert broker.result_backend is not None
    result_ttl = broker.result_backend.result_ex_time
    assert result_ttl is not None
    assert result_ttl == app_settings.TASKIQ_RESULT_TTL_SECONDS
    assert result_ttl > 0


def test_kubernetes_reference_uses_the_dedicated_task_redis() -> None:
    configmap = yaml.safe_load(K8S_CONFIGMAP_FILE.read_text(encoding="utf-8"))
    keda_documents = list(yaml.safe_load_all(K8S_KEDA_FILE.read_text(encoding="utf-8")))
    scaled_object = keda_documents[1]
    redis_metadata = scaled_object["spec"]["triggers"][0]["metadata"]

    assert configmap["data"]["REDIS_HOST"] == "redis-cache"
    assert configmap["data"]["TASKIQ_REDIS_HOST"] == "redis-taskiq"
    assert redis_metadata["address"].startswith("redis-taskiq.")
    assert redis_metadata["databaseIndex"] == "0"
