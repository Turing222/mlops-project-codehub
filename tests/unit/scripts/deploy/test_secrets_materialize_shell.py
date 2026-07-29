"""Shell wiring tests for the EC2 Secrets Manager materialize entrypoint.

职责：验证 deploy env 到 Python CLI 参数的映射；边界：使用 fake uv，不访问 AWS。
副作用：仅写入 pytest 临时目录。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = PROJECT_ROOT / "scripts" / "deploy" / "secrets-materialize.sh"


def _run_script(
    tmp_path: Path,
    env_content: str,
    *,
    fake_uv: bool,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    env_file = tmp_path / "deploy.env"
    env_file.write_text(env_content, encoding="utf-8")
    log_file = tmp_path / "uv-args.txt"
    path = os.environ["PATH"]

    if fake_uv:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        uv_path = bin_dir / "uv"
        uv_path.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >"$FAKE_UV_LOG"\n',
            encoding="utf-8",
        )
        uv_path.chmod(0o755)
        path = f"{bin_dir}:{path}"

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        env={
            "PATH": path,
            "DEPLOY_ENV_FILE": str(env_file),
            "FAKE_UV_LOG": str(log_file),
        },
        text=True,
    )
    return result, log_file


def test_materialize_shell_maps_deploy_env_to_cli_args(tmp_path: Path) -> None:
    result, log_file = _run_script(
        tmp_path,
        "\n".join(
            [
                "DEPLOY_SECRET_SOURCE=aws",
                "DEPLOY_SECRET_DIR=/run/dewflow-test-secrets",
                "DEPLOY_RUNTIME_SECRET_ID=dewflow-test-runtime",
                "DEPLOY_AWS_REGION=us-west-2",
            ]
        ),
        fake_uv=True,
    )

    assert result.returncode == 0
    assert log_file.read_text(encoding="utf-8").strip() == (
        "run --frozen python scripts/deploy/secret_bundle.py materialize "
        "--secret-id dewflow-test-runtime "
        "--directory /run/dewflow-test-secrets "
        "--region us-west-2"
    )


def test_materialize_shell_rejects_relative_aws_target(tmp_path: Path) -> None:
    result, _ = _run_script(
        tmp_path,
        "\n".join(
            [
                "DEPLOY_SECRET_SOURCE=aws",
                "DEPLOY_SECRET_DIR=secrets/ec2",
            ]
        ),
        fake_uv=True,
    )

    assert result.returncode == 1
    assert "must be an absolute runtime path" in result.stderr
