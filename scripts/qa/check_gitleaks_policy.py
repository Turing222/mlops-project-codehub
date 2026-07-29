#!/usr/bin/env python3
"""Validate that Gitleaks exceptions stay narrow and public paths remain scanned.

职责：审计仓库 Gitleaks 配置和 fingerprint，并可用 synthetic secret 验证 docs 扫描；
边界：不读取真实 secret；副作用：可在系统临时目录创建并自动清理测试文件。
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTECTED_PATH_SAMPLES = (
    "docs/standards/example.md",
    "work-items/active/example/task-plan.md",
    "tests/unit/example.py",
    "frontend/apps/admin/e2e/example.spec.ts",
    "evals/example.py",
    "perf/example.py",
    ".env.smoke.template",
    "deploy/example.env",
    "deploy/config.example",
    "deploy/config.example.yaml",
)
COMMIT_FINGERPRINT = re.compile(
    r"^(?P<commit>[0-9a-f]{40}):(?P<path>[^:]+):(?P<rule>[^:]+):(?P<line>[1-9]\d*)$"
)


def audit_gitleaks_config(config_path: Path) -> list[str]:
    try:
        with config_path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        return [f"{config_path}: unable to read valid TOML: {error}"]

    findings = []
    allowlists = config.get("allowlists", [])
    if not isinstance(allowlists, list):
        return [f"{config_path}: top-level allowlists must be an array of tables"]

    for index, allowlist in enumerate(allowlists, start=1):
        if not isinstance(allowlist, dict):
            findings.append(f"{config_path}: allowlist {index} must be a table")
            continue

        paths = allowlist.get("paths", [])
        target_rules = allowlist.get("targetRules", [])
        has_value_filter = bool(allowlist.get("regexes") or allowlist.get("stopwords"))
        condition = str(allowlist.get("condition", "OR")).upper()

        if allowlist.get("commits"):
            findings.append(
                f"{config_path}: allowlist {index} skips commits; use a commit-scoped "
                ".gitleaksignore fingerprint"
            )
        if not target_rules or condition != "AND" or not paths or not has_value_filter:
            findings.append(
                f"{config_path}: allowlist {index} must combine targetRules, paths, "
                'and regexes/stopwords with condition = "AND"'
            )

        for path_pattern in paths if isinstance(paths, list) else []:
            try:
                compiled = re.compile(str(path_pattern))
            except re.error as error:
                findings.append(
                    f"{config_path}: allowlist {index} has invalid path regex: {error}"
                )
                continue
            matched_paths = [
                path for path in PROTECTED_PATH_SAMPLES if compiled.search(path)
            ]
            if matched_paths:
                findings.append(
                    f"{config_path}: allowlist {index} exempts protected public paths: "
                    f"{', '.join(matched_paths)}"
                )
    return findings


def audit_gitleaks_ignore(ignore_path: Path) -> list[str]:
    try:
        lines = ignore_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return [f"{ignore_path}: unable to read fingerprint file: {error}"]

    findings = []
    seen = set()
    for line_number, raw_line in enumerate(lines, start=1):
        fingerprint = raw_line.strip()
        if not fingerprint or fingerprint.startswith("#"):
            continue
        if fingerprint in seen:
            findings.append(f"{ignore_path}:{line_number}: duplicate fingerprint")
            continue
        seen.add(fingerprint)
        if not COMMIT_FINGERPRINT.fullmatch(fingerprint):
            findings.append(
                f"{ignore_path}:{line_number}: fingerprint must include commit, path, "
                "rule, and line"
            )
    return findings


def verify_gitleaks_scans_docs(config_path: Path, binary: str) -> list[str]:
    executable = shutil.which(binary)
    if executable is None:
        return [f"gitleaks verification requested but binary was not found: {binary}"]

    with tempfile.TemporaryDirectory(prefix="dewflow-gitleaks-policy-") as temp_dir:
        source = Path(temp_dir)
        docs_file = source / "docs" / "synthetic-leak.md"
        docs_file.parent.mkdir(parents=True)
        synthetic_secret = "".join(("a9F3kL7m", "N2pQ8rS4", "tV6wX1yZ", "5bC0dE7h"))
        docs_file.write_text(f'api_key = "{synthetic_secret}"\n', encoding="utf-8")
        result = subprocess.run(
            [
                executable,
                "dir",
                "--config",
                str(config_path),
                "--redact",
                "--no-banner",
                "--exit-code",
                "17",
                str(source),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    if result.returncode == 17:
        return []
    if result.returncode == 0:
        return ["gitleaks did not detect the synthetic secret under docs/"]
    return [f"gitleaks verification failed with exit code {result.returncode}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-gitleaks", action="store_true")
    parser.add_argument("--gitleaks-path", default="gitleaks")
    args = parser.parse_args()

    findings = audit_gitleaks_config(REPO_ROOT / ".gitleaks.toml")
    findings.extend(audit_gitleaks_ignore(REPO_ROOT / ".gitleaksignore"))
    if args.verify_gitleaks:
        findings.extend(
            verify_gitleaks_scans_docs(
                REPO_ROOT / ".gitleaks.toml",
                args.gitleaks_path,
            )
        )

    if findings:
        print("Gitleaks policy check failed:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print("Gitleaks policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
