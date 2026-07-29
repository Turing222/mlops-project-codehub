"""Public repository sensitive-value scanner unit tests.

职责：覆盖公开目录、项目标识符、占位符和脱敏报告；边界：仅写临时文件；副作用：无。
"""

from pathlib import Path

import pytest

from scripts.qa.check_no_sensitive_values import audit_paths


def _write(repo_root: Path, relative_path: Path, content: str) -> None:
    target = repo_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    ("relative_path", "content_parts", "rule_name"),
    [
        (
            Path("docs/platform/runbook.md"),
            ("AWS_ACCOUNT_ID=", "908172", "635445"),
            "aws-account-id",
        ),
        (
            Path("work-items/active/example/task-plan.md"),
            ("arn:aws-us-gov:iam::", "908172", "635445", ":role/deploy"),
            "aws-account-id",
        ),
        (
            Path(".env.smoke.template"),
            ("VPC_ID=vpc-", "0123456789abcdef0"),
            "aws-network-resource-id",
        ),
        (
            Path("deploy/config.example"),
            (
                "POSTGRES_SERVER=database.",
                "abc123def456",
                ".us-east-1.rds.amazonaws.com",
            ),
            "rds-endpoint",
        ),
        (
            Path("tests/unit/fixture.txt"),
            (
                "TUNNEL_ID=",
                "123e4567-e89b-12d3-a456-",
                "426614174000",
            ),
            "cloudflare-tunnel-id",
        ),
        (
            Path("evals/fixture.txt"),
            ("INSTANCE_ID=i-", "0123456789abcdef0"),
            "ec2-instance-id",
        ),
        (
            Path("perf/fixture.txt"),
            ("SECURITY_GROUP_ID=sg-", "0123456789abcdef0"),
            "aws-network-resource-id",
        ),
        (
            Path("frontend/apps/admin/e2e/fixture.txt"),
            (
                "CLOUDFLARE_API_TOKEN=",
                "abcDEF123_ghiJKL456_",
                "mnopQR789_stuvWX012",
            ),
            "cloudflare-api-token",
        ),
    ],
)
def test_audit_paths_rejects_sensitive_values_in_public_content(
    tmp_path: Path,
    relative_path: Path,
    content_parts: tuple[str, ...],
    rule_name: str,
) -> None:
    content = "".join(content_parts)
    _write(tmp_path, relative_path, content)

    findings = audit_paths(tmp_path, [relative_path])

    assert len(findings) == 1
    assert f"[{rule_name}]" in findings[0]
    assert findings[0].startswith(f"{relative_path}:1:")
    assert content not in findings[0]


def test_audit_paths_accepts_placeholders_and_reserved_samples(
    tmp_path: Path,
) -> None:
    relative_path = Path("docs/platform/example.md")
    reserved_account_id = "".join(("123456", "789012"))
    reserved_access_key = "".join(("AKIA", "11111111", "11111111"))
    content = "\n".join(
        (
            "AWS_ACCOUNT_ID=<AWS_ACCOUNT_ID>",
            "VPC_ID=<VPC_ID>",
            "TUNNEL_ID=<TUNNEL_ID>",
            f"AWS_ACCOUNT_ID={reserved_account_id}",
            f"AWS_ACCESS_KEY_ID={reserved_access_key}",
        )
    )
    _write(tmp_path, relative_path, content)

    assert audit_paths(tmp_path, [relative_path]) == []


def test_audit_paths_ignores_non_utf8_files(tmp_path: Path) -> None:
    relative_path = Path("docs/screenshot.bin")
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe\x00\x00")

    assert audit_paths(tmp_path, [relative_path]) == []
