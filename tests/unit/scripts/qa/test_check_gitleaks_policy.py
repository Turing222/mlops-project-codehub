"""Gitleaks policy guard unit tests.

职责：覆盖配置 allowlist、fingerprint 和 synthetic docs 验证；边界：使用临时文件与假 binary；副作用：无。
"""

from pathlib import Path

import pytest

from scripts.qa.check_gitleaks_policy import (
    REPO_ROOT,
    audit_gitleaks_config,
    audit_gitleaks_ignore,
    verify_gitleaks_scans_docs,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_repository_gitleaks_policy_has_no_broad_exemptions() -> None:
    assert audit_gitleaks_config(REPO_ROOT / ".gitleaks.toml") == []
    assert audit_gitleaks_ignore(REPO_ROOT / ".gitleaksignore") == []


@pytest.mark.parametrize(
    "path_pattern",
    (
        "^docs/",
        "^work-items/",
        "^tests/",
        "^frontend/apps/admin/e2e/",
        "^evals/",
        "^perf/",
        r".*\.template$",
        r".*\.example$",
        r".*\.example.*",
        r"^deploy/.*\.example.*",
    ),
)
def test_audit_gitleaks_config_rejects_public_path_exemptions(
    tmp_path: Path,
    path_pattern: str,
) -> None:
    config_path = tmp_path / ".gitleaks.toml"
    _write(
        config_path,
        f"""
[extend]
useDefault = true

[[allowlists]]
paths = ['''{path_pattern}''']
""",
    )

    findings = audit_gitleaks_config(config_path)

    assert any("exempts protected public paths" in finding for finding in findings)


def test_audit_gitleaks_config_accepts_precise_rule_and_value_scope(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".gitleaks.toml"
    _write(
        config_path,
        """
[extend]
useDefault = true

[[allowlists]]
targetRules = ["generic-api-key"]
condition = "AND"
paths = ['''^tests/fixtures/known-fake\\.txt$''']
regexTarget = "match"
regexes = ['''^known-fake-value$''']
""",
    )

    assert audit_gitleaks_config(config_path) == []


def test_audit_gitleaks_config_rejects_regex_only_global_allowlist(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".gitleaks.toml"
    _write(
        config_path,
        """
[extend]
useDefault = true

[[allowlists]]
regexes = ['''(?i)test|fake|example''']
""",
    )

    findings = audit_gitleaks_config(config_path)

    assert any("must combine targetRules" in finding for finding in findings)


def test_audit_gitleaks_ignore_accepts_commit_scoped_fingerprints(
    tmp_path: Path,
) -> None:
    ignore_path = tmp_path / ".gitleaksignore"
    _write(
        ignore_path,
        "\n".join(
            (
                "# known fixture",
                f"{'a' * 40}:tests/fixture.py:generic-api-key:12",
                "",
            )
        ),
    )

    assert audit_gitleaks_ignore(ignore_path) == []


def test_audit_gitleaks_ignore_rejects_global_and_duplicate_fingerprints(
    tmp_path: Path,
) -> None:
    ignore_path = tmp_path / ".gitleaksignore"
    commit_fingerprint = f"{'b' * 40}:tests/fixture.py:generic-api-key:12"
    _write(
        ignore_path,
        "\n".join(
            (
                "tests/fixture.py:generic-api-key:12",
                commit_fingerprint,
                commit_fingerprint,
            )
        ),
    )

    findings = audit_gitleaks_ignore(ignore_path)

    assert any("must include commit" in finding for finding in findings)
    assert any("duplicate fingerprint" in finding for finding in findings)


@pytest.mark.parametrize(
    ("exit_code", "expected_fragment"), [(17, None), (0, "did not detect")]
)
def test_verify_gitleaks_scans_docs_requires_a_detection(
    tmp_path: Path,
    exit_code: int,
    expected_fragment: str | None,
) -> None:
    config_path = tmp_path / ".gitleaks.toml"
    _write(config_path, "[extend]\nuseDefault = true\n")
    binary = tmp_path / "fake-gitleaks"
    _write(binary, f"#!/usr/bin/env sh\nexit {exit_code}\n")
    binary.chmod(0o755)

    findings = verify_gitleaks_scans_docs(config_path, str(binary))

    if expected_fragment is None:
        assert findings == []
    else:
        assert any(expected_fragment in finding for finding in findings)
