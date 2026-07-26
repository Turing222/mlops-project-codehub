#!/usr/bin/env python3
"""Block real deployment identifiers and credentials from entering the repository.

仓库是公开的：真实账号 ID、实例 ID、域名、endpoint 和密钥一律只存在于 GitHub repo
variables、SSM 参数库或部署主机上，仓库内只允许占位符。测试样例请使用本文件
ALLOWED_SAMPLES 中登记的保留值。
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 允许出现的公开保留值：RFC 5737/2606 文档地址、明显的假样例、代码内默认占位符。
ALLOWED_SAMPLES = frozenset(
    {
        "AKIA1111111111111111",
        "AKIAIOSFODNN7EXAMPLE",
        "13800000000",
        "13800138000",
        "13812345678",
        "123456789012",
    }
)

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "snapshots",
    }
)

SKIP_SUFFIXES = frozenset({".lock", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff2"})

# 本文件自身登记了模式与样例，扫描时跳过，避免自命中。
SELF_PATH = Path(__file__).relative_to(REPO_ROOT)


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    hint: str


RULES: tuple[Rule, ...] = (
    Rule(
        "aws-access-key-id",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "AWS access key id must never be committed; rotate it immediately if real.",
    ),
    Rule(
        "aws-account-id",
        re.compile(r"\b\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com\b"),
        "Use <AWS_ACCOUNT_ID>.dkr.ecr.<region>.amazonaws.com; real registry host "
        "belongs in repo variables.",
    ),
    Rule(
        "ec2-instance-id",
        re.compile(r"\bi-[0-9a-f]{17}\b"),
        "Use <EC2_INSTANCE_ID>; the real id belongs in repo variables.",
    ),
    Rule(
        "rds-endpoint",
        re.compile(r"\b[a-z0-9-]+\.[a-z0-9]{10,}\.[a-z0-9-]+\.rds\.amazonaws\.com\b"),
        "Use <RDS_ENDPOINT>; the real endpoint belongs in deploy/.env.ec2 on the host.",
    ),
    Rule(
        "cloudflare-tunnel-id",
        re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
            r"\.cfargotunnel\.com\b"
        ),
        "Use <TUNNEL_ID>.cfargotunnel.com; the real tunnel id stays in Cloudflare.",
    ),
    Rule(
        "private-key-block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        "Private keys must never be committed.",
    ),
    Rule(
        "cloudflare-api-token",
        re.compile(r"\bCLOUDFLARE_API_TOKEN\s*[:=]\s*['\"]?[A-Za-z0-9_-]{30,}"),
        "Cloudflare API tokens belong in a local file or GitHub secrets.",
    ),
)
# 通用凭据（高熵字符串、第三方 token）由 security-ci 的 gitleaks job 负责，本脚本
# 只覆盖项目特有的部署标识符，避免与测试固件里的假密码相互误伤。


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = []
    for raw in result.stdout.split("\0"):
        if not raw:
            continue
        path = Path(raw)
        if path == SELF_PATH:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        paths.append(path)
    return paths


def _violations_in(path: Path) -> list[str]:
    try:
        content = (REPO_ROOT / path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return []

    findings = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for rule in RULES:
            for match in rule.pattern.finditer(line):
                if match.group(0) in ALLOWED_SAMPLES:
                    continue
                findings.append(f"{path}:{line_number}: [{rule.name}] {rule.hint}")
    return findings


def main() -> int:
    findings = []
    for path in _tracked_files():
        findings.extend(_violations_in(path))

    if findings:
        print("Sensitive value check failed:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nReplace real values with placeholders. Deployment identifiers live in "
            "GitHub repo variables; secrets live in SSM Parameter Store or "
            "secrets/<env>/*.txt on the host.",
            file=sys.stderr,
        )
        return 1

    print("Sensitive value check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
