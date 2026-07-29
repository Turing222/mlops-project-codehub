"""Tests for deploy env precedence helpers in scripts/lib/common.sh.

The tests execute the real shell functions with temporary env files so the
Makefile marker contract stays covered without starting Docker.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMMON_SH = PROJECT_ROOT / "scripts" / "lib" / "common.sh"


def _run_common_bash(
    script: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"]}
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            f"set -euo pipefail; source {COMMON_SH}; {script}",
        ],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )


def _deploy_control_env_value(
    tmp_path: Path,
    env_file_content: str,
    name: str,
    default: str,
    extra_env: dict[str, str] | None = None,
) -> str:
    env_file = tmp_path / "deploy.env"
    env_file.write_text(env_file_content, encoding="utf-8")

    env = {"DEPLOY_ENV_FILE": str(env_file)}
    if extra_env:
        env.update(extra_env)

    result = _run_common_bash(f"deploy_control_env_value {name!r} {default!r}", env)
    return result.stdout.removesuffix("\n")


def _load_deploy_aws_region(
    tmp_path: Path,
    env_file_content: str,
    extra_env: dict[str, str] | None = None,
) -> str:
    env_file = tmp_path / "deploy.env"
    env_file.write_text(env_file_content, encoding="utf-8")

    env = {"DEPLOY_ENV_FILE": str(env_file)}
    if extra_env:
        env.update(extra_env)

    result = _run_common_bash(
        "load_deploy_env; printenv DEPLOY_AWS_REGION",
        env,
    )
    return result.stdout.removesuffix("\n")


def test_deploy_env_file_wins_over_makefile_default_marker(tmp_path: Path) -> None:
    value = _deploy_control_env_value(
        tmp_path,
        "DEPLOY_BASE_URL=https://deploy.example.com\n",
        "DEPLOY_BASE_URL",
        "http://localhost",
        {
            "DEPLOY_BASE_URL": "http://localhost",
            "DEPLOY_BASE_URL_EXPLICIT": "",
        },
    )

    assert value == "https://deploy.example.com"


def test_explicit_value_equal_to_default_overrides_env_file(tmp_path: Path) -> None:
    value = _deploy_control_env_value(
        tmp_path,
        "DEPLOY_PULL_IMAGES=true\n",
        "DEPLOY_PULL_IMAGES",
        "false",
        {
            "DEPLOY_PULL_IMAGES": "false",
            "DEPLOY_PULL_IMAGES_EXPLICIT": "1",
        },
    )

    assert value == "false"


def test_direct_shell_env_value_overrides_env_file_without_marker(
    tmp_path: Path,
) -> None:
    value = _deploy_control_env_value(
        tmp_path,
        "DEPLOY_LOG_TAIL=500\n",
        "DEPLOY_LOG_TAIL",
        "200",
        {"DEPLOY_LOG_TAIL": "200"},
    )

    assert value == "200"


def test_explicit_empty_value_overrides_env_file(tmp_path: Path) -> None:
    value = _deploy_control_env_value(
        tmp_path,
        "RAG_RERANK_PROVIDER=bifrost\n",
        "RAG_RERANK_PROVIDER",
        "",
        {"RAG_RERANK_PROVIDER": ""},
    )

    assert value == ""


def test_env_file_value_falls_back_to_default_when_missing(tmp_path: Path) -> None:
    value = _deploy_control_env_value(
        tmp_path,
        "DEPLOY_PULL_IMAGES=true\n",
        "DEPLOY_LOG_TAIL",
        "200",
    )

    assert value == "200"


def test_load_deploy_env_exports_default_region_when_missing(tmp_path: Path) -> None:
    value = _load_deploy_aws_region(
        tmp_path,
        "APP_ENV=prod\n",
        {
            "DEPLOY_AWS_REGION": "us-west-2",
            "DEPLOY_AWS_REGION_EXPLICIT": "",
        },
    )

    assert value == "us-west-2"


def test_load_deploy_env_exports_region_from_env_file(tmp_path: Path) -> None:
    value = _load_deploy_aws_region(
        tmp_path,
        "DEPLOY_AWS_REGION=eu-central-1\n",
        {
            "DEPLOY_AWS_REGION": "us-west-2",
            "DEPLOY_AWS_REGION_EXPLICIT": "",
        },
    )

    assert value == "eu-central-1"


def test_ensure_deploy_secret_file_sets_container_readable_permissions(
    tmp_path: Path,
) -> None:
    secret_path = tmp_path / "secrets" / "secret_key.txt"

    result = _run_common_bash(
        (
            "ensure_deploy_secret_file DEPLOY_SECRET_KEY_FILE empty; "
            'stat -c "%a" "$(dirname "$DEPLOY_SECRET_KEY_FILE")"; '
            'stat -c "%a" "$DEPLOY_SECRET_KEY_FILE"'
        ),
        {"DEPLOY_SECRET_KEY_FILE": str(secret_path)},
    )

    assert result.stdout.splitlines()[-2:] == ["700", "644"]
