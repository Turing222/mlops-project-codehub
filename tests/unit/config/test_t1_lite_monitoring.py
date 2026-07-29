"""T1-Lite monitoring deployment contract tests.

职责：锁定 worker/scheduler module wiring、CloudWatch filters、dead-man 策略与受控送达脚本。
边界：只读取仓库资产，不调用 AWS、Docker、Redis 或 PostgreSQL。
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OPERABILITY_MODULE = "backend.worker.tasks.operability_tasks"


def test_worker_and_scheduler_load_operability_task() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]

    assert (
        OPERABILITY_MODULE in services["task_worker"]["environment"]["TASKIQ_MODULES"]
    )
    assert (
        OPERABILITY_MODULE
        in services["credit_scheduler"]["environment"]["TASKIQ_SCHEDULER_MODULES"]
    )
    assert OPERABILITY_MODULE in services["credit_scheduler"]["command"]
    assert OPERABILITY_MODULE in (PROJECT_ROOT / "Dockerfile").read_text()


def test_cloudwatch_setup_contains_minimum_t1_lite_signal_set() -> None:
    script = (PROJECT_ROOT / "deploy/monitoring/cloudwatch-setup.sh").read_text(
        encoding="utf-8"
    )

    for filter_name in (
        "dewflow-api-5xx",
        "dewflow-api-latency",
        "dewflow-taskiq-queue-depth",
        "dewflow-oldest-pending",
        "dewflow-t1-lite-heartbeat",
        "dewflow-terminal-task-failure",
        "dewflow-redis-risk",
        "dewflow-operability-probe-failure",
        "dewflow-t1-lite-synthetic-delivery",
    ):
        assert f'put_metric_filter "{filter_name}"' in script

    assert '"LessThanThreshold" "$alarm_period" "1" "breaching"' in script
    assert "chat_generation_recovery_failed" in script
    assert "knowledge_outbox_dead" in script
    assert "redis_restart_detected" in script


def test_cloudwatch_assets_use_resolved_deploy_region() -> None:
    for relative_path in (
        "scripts/deploy/ec2-check.sh",
        "deploy/monitoring/cloudwatch-setup.sh",
        "deploy/monitoring/cloudwatch-verify-delivery.sh",
    ):
        script = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert 'region="$DEPLOY_AWS_REGION"' in script

    for relative_path in (
        "deploy/docker-compose.yml",
        "deploy/docker-compose.local-postgres.yml",
    ):
        compose = yaml.safe_load((PROJECT_ROOT / relative_path).read_text())
        assert compose["x-logging"]["options"]["awslogs-region"] == (
            "${DEPLOY_AWS_REGION:-us-west-2}"
        )


def test_delivery_verification_is_bounded_and_requires_confirmed_receiver() -> None:
    script = (
        PROJECT_ROOT / "deploy/monitoring/cloudwatch-verify-delivery.sh"
    ).read_text(encoding="utf-8")

    assert "t1_lite_synthetic_alarm" in script
    assert "PendingConfirmation" in script
    assert "confirmed receiver" in script
    assert "for ((attempt = 1; attempt <= poll_attempts; attempt += 1))" in script
    assert "while true" not in script.lower()
    assert "Alarm state alone is not delivery evidence" in script
    assert "require_cmd uv" in script
    assert script.count("uv run python") == 2
    assert "require_cmd python" not in script
