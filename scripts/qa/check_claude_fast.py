#!/usr/bin/env python3
"""Fast project standards checks for touched files or directories.

The checks are agent-generic: Claude hooks can call them automatically, while
humans, CI jobs, and other agents can run the same script directly.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

LEGACY_TEXT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"Work-Item Attachment"),
        "Use 'Attach to Existing Work Item' instead.",
    ),
    (
        re.compile(r"lightweight dependencies"),
        "Use workstreams / deps / open_decisions terminology instead.",
    ),
    (re.compile(r"<task-slug>"), "Use <work-item-slug> in work-items guidance."),
    (
        re.compile(r"\btask identity\b"),
        "Use work-item identity in durable planning docs.",
    ),
    (re.compile(r"\btask slug\b"), "Use work-item slug in durable planning docs."),
    (
        re.compile(r"\bactive[- ]task match\b"),
        "Use active work-item match wording instead.",
    ),
    (
        re.compile(r"\bcreate a new task\b"),
        "Use create a new work item wording instead.",
    ),
    (
        re.compile(r"\bnew task identity\b"),
        "Use new work-item identity wording instead.",
    ),
)

LEGACY_OPERATIONAL_LOG_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"Worker rerank 构造失败"),
        "Use event=worker_rerank_init_degraded with an English developer log.",
    ),
    (
        re.compile(r"断路器打开"),
        "Use event=circuit_breaker_opened with an English developer log.",
    ),
    (
        re.compile(r"断路器恢复"),
        "Use event=circuit_breaker_recovered with an English developer log.",
    ),
    (
        re.compile(r"断路器进入半开状态"),
        "Use event=circuit_breaker_half_open with an English developer log.",
    ),
    (
        re.compile(r"断路器重新打开"),
        "Use event=circuit_breaker_reopened with an English developer log.",
    ),
)

TEXT_FILE_SUFFIXES = {
    ".md",
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
}
EXCLUDED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "htmlcov",
}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def _iter_line_matches(
    path: Path,
    text: str,
    patterns: tuple[tuple[re.Pattern[str], str], ...],
) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern, message in patterns:
            if pattern.search(line):
                violations.append(Violation(path=path, line=lineno, message=message))
    return violations


def _check_manifest_language(path: Path, text: str) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if CJK_RE.search(line):
            violations.append(
                Violation(
                    path=path,
                    line=lineno,
                    message="manifest.yaml must stay fully English.",
                )
            )
    return violations


def _check_task_plan_language(path: Path, text: str) -> list[Violation]:
    if CJK_RE.search(text):
        return []
    return [
        Violation(
            path=path,
            line=1,
            message="task-plan.md should contain Chinese narrative prose.",
        )
    ]


def _iter_target_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix.lower() in TEXT_FILE_SUFFIXES and path not in seen:
                files.append(path)
                seen.add(path)
            continue

        for child in sorted(path.rglob("*")):
            if not child.is_file():
                continue
            if child.suffix.lower() not in TEXT_FILE_SUFFIXES:
                continue
            if any(part in EXCLUDED_DIR_NAMES for part in child.parts):
                continue
            if child not in seen:
                files.append(child)
                seen.add(child)

    return files


def audit_paths(paths: list[Path]) -> list[Violation]:
    violations: list[Violation] = []

    for raw_path in _iter_target_files(paths):
        text = _read_text(raw_path)
        if text is None:
            continue

        normalized = raw_path.as_posix()
        is_work_items = "work-items/" in normalized
        is_docs_or_skills = normalized.startswith(
            ("docs/", "work-items/", ".codex/skills/")
        )
        is_backend_python = (
            normalized.startswith("backend/") and raw_path.suffix == ".py"
        )

        if is_docs_or_skills:
            violations.extend(_iter_line_matches(raw_path, text, LEGACY_TEXT_PATTERNS))

        if is_backend_python:
            violations.extend(
                _iter_line_matches(raw_path, text, LEGACY_OPERATIONAL_LOG_PATTERNS)
            )

        if is_work_items and raw_path.name == "manifest.yaml":
            violations.extend(_check_manifest_language(raw_path, text))

        if is_work_items and raw_path.name == "task-plan.md":
            violations.extend(_check_task_plan_language(raw_path, text))

    return violations


def main(argv: list[str]) -> int:
    if not argv:
        print(
            "Usage: check_claude_fast.py <file-or-dir> [<file-or-dir> ...]",
            file=sys.stderr,
        )
        return 2

    paths = [Path(arg) for arg in argv]
    violations = audit_paths(paths)
    if not violations:
        return 0

    print("Claude fast audit failed:")
    for violation in violations:
        print(violation.format())
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
