#!/usr/bin/env python3
"""Generate a lightweight local PR readiness report.

The report is intentionally fact-first: it captures git state, changed files,
diff stats, and a validation checklist without trying to infer intent.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "logs" / "pr"


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def _fenced(value: str, *, language: str = "text") -> str:
    content = value.strip() or "(none)"
    return f"```{language}\n{content}\n```"


def _checkbox(label: str, completed: set[str]) -> str:
    mark = "x" if label in completed else " "
    return f"- [{mark}] `{label}`"


def _build_report(*, completed: set[str]) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    branch = _run_git(["branch", "--show-current"])
    head = _run_git(["rev-parse", "--short", "HEAD"])
    status = _run_git(["status", "--short"])
    diff_stat = _run_git(["diff", "--stat"])
    staged_diff_stat = _run_git(["diff", "--cached", "--stat"])
    changed_files = _run_git(["diff", "--name-only"])
    staged_files = _run_git(["diff", "--cached", "--name-only"])
    untracked_files = _run_git(["ls-files", "--others", "--exclude-standard"])

    validation_commands = [
        "make frontend-check",
        "make frontend-typecheck",
        "E2E_SMOKE_USER=seed_admin E2E_SMOKE_PASS='SeedPass123!' make frontend-e2e-smoke",
        "uv run pytest tests/unit/config/test_llm_config.py",
        "make qa-test-unit",
        "docker compose --profile bifrost --env-file .env.smoke -f docker-compose.db.yml config --quiet",
    ]

    lines = [
        "# PR Readiness Report",
        "",
        f"- Generated: {now}",
        f"- Branch: `{branch or '(detached)'}`",
        f"- HEAD: `{head or '(unknown)'}`",
        "",
        "## Summary",
        "",
        "- What changed: TODO",
        "- Why: TODO",
        "- User-visible impact: TODO",
        "",
        "## Validation",
        "",
        *(_checkbox(command, completed) for command in validation_commands),
        "",
        "## Risk Notes",
        "",
        "- TODO: note config, migration, data, auth, or rollout risks.",
        "- TODO: note manual checks or follow-up cleanup.",
        "",
        "## Git Status",
        "",
        _fenced(status),
        "",
        "## Diff Stat",
        "",
        _fenced(diff_stat),
        "",
        "## Staged Diff Stat",
        "",
        _fenced(staged_diff_stat),
        "",
        "## Changed Files",
        "",
        _fenced(changed_files),
        "",
        "## Staged Files",
        "",
        _fenced(staged_files),
        "",
        "## Untracked Files",
        "",
        _fenced(untracked_files),
        "",
        "## Smoke Notes",
        "",
        "- LLM provider: `bifrost` when `.env.smoke` sets `LLM_PROVIDER=bifrost`.",
        "- Bifrost key requirement: `BIFROST_API_KEY` must start with `sk-bf-`.",
        "- Frontend smoke e2e requires `E2E_SMOKE_USER` and `E2E_SMOKE_PASS`.",
        "",
    ]
    return "\n".join(lines)


def _parse_completed(values: list[str]) -> set[str]:
    completed: set[str] = set()
    for value in values:
        completed.update(item.strip() for item in value.split(",") if item.strip())
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Report path. Defaults to logs/pr/pr-report-<timestamp>.md.",
    )
    parser.add_argument(
        "--completed",
        action="append",
        default=[],
        help="Validation command to mark complete. May be passed multiple times or comma-separated.",
    )
    args = parser.parse_args()

    output = args.output
    if output is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output = DEFAULT_REPORT_DIR / f"pr-report-{timestamp}.md"
    if not output.is_absolute():
        output = PROJECT_ROOT / output

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _build_report(completed=_parse_completed(args.completed)),
        encoding="utf-8",
    )
    print(os.path.relpath(output, PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
