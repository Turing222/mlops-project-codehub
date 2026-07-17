"""Chat recovery worker/scheduler deployment contract tests.

职责：验证 Compose、Kubernetes 与镜像默认值都会加载 recovery task module。
边界：只读取仓库配置，不启动容器或 scheduler；副作用：无。
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RECOVERY_MODULE = "backend.worker.tasks.chat_recovery_tasks"


def test_production_compose_loads_recovery_in_worker_and_scheduler() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]

    assert RECOVERY_MODULE in services["task_worker"]["environment"]["TASKIQ_MODULES"]
    scheduler = services["credit_scheduler"]
    assert RECOVERY_MODULE in scheduler["environment"]["TASKIQ_SCHEDULER_MODULES"]
    assert RECOVERY_MODULE in scheduler["command"]


def test_kubernetes_worker_and_scheduler_load_recovery_module() -> None:
    worker = yaml.safe_load(
        (PROJECT_ROOT / "deploy/k8s/worker-deployment.yaml").read_text(encoding="utf-8")
    )
    scheduler = yaml.safe_load(
        (PROJECT_ROOT / "deploy/k8s/credit-scheduler-deployment.yaml").read_text(
            encoding="utf-8"
        )
    )
    worker_container = worker["spec"]["template"]["spec"]["containers"][0]
    scheduler_container = scheduler["spec"]["template"]["spec"]["containers"][0]

    worker_env = {item["name"]: item["value"] for item in worker_container["env"]}
    scheduler_env = {item["name"]: item["value"] for item in scheduler_container["env"]}
    assert RECOVERY_MODULE in worker_env["TASKIQ_MODULES"]
    assert RECOVERY_MODULE in scheduler_env["TASKIQ_SCHEDULER_MODULES"]
    assert RECOVERY_MODULE in scheduler_container["command"]


def test_worker_image_default_loads_recovery_module() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert RECOVERY_MODULE in dockerfile
