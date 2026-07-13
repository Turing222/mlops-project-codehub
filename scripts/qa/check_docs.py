#!/usr/bin/env python3
"""Validate Dewflow documentation structure, naming, links, and layout."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCS_ROOT = REPO_ROOT / "docs"
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
ASSESSMENT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
LEGACY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-legacy\.md$")
TABLE_SEPARATOR_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")
ASSESSMENT_METADATA = ("日期", "范围", "性质", "证据基线", "状态")


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def _fence_line(line: str) -> str:
    stripped = line.lstrip()
    while stripped.startswith(">"):
        stripped = stripped[1:].lstrip()
    return stripped


def _normalized_table_separator(line: str) -> str:
    cells = line.strip()[1:-1].split("|")
    normalized: list[str] = []
    for raw_cell in cells:
        cell = raw_cell.strip()
        left = cell.startswith(":")
        right = cell.endswith(":")
        normalized.append(f"{':' if left else ''}---{':' if right else ''}")
    return f"| {' | '.join(normalized)} |"


def _link_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    if not target or target.startswith(("#", "/", "http://", "https://")):
        return None
    if target.startswith(("mailto:", "tel:")):
        return None
    return unquote(target.split("#", maxsplit=1)[0])


def _audit_markdown(path: Path) -> list[Violation]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    violations: list[Violation] = []
    fence: str | None = None
    h1_count = 0
    previous_heading = 0

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r\n")
        if line != line.rstrip():
            violations.append(Violation(path, line_number, "trailing whitespace"))

        fence_line = _fence_line(line)
        if fence is not None:
            if fence_line.startswith(fence):
                fence = None
            continue
        if fence_line.startswith(("```", "~~~")):
            fence = fence_line[:3]
            if not fence_line[3:].strip():
                violations.append(
                    Violation(path, line_number, "fenced code block needs a language")
                )
            continue

        heading = re.match(r"^(#{1,6})\s+\S", line)
        if heading:
            level = len(heading.group(1))
            h1_count += level == 1
            if previous_heading and level > previous_heading + 1:
                violations.append(
                    Violation(
                        path,
                        line_number,
                        f"heading level jumps from H{previous_heading} to H{level}",
                    )
                )
            previous_heading = level

        stripped = line.strip()
        if TABLE_SEPARATOR_RE.fullmatch(
            stripped
        ) and stripped != _normalized_table_separator(stripped):
            violations.append(
                Violation(path, line_number, "table separator must use spaced ---")
            )

    if fence is not None:
        violations.append(Violation(path, len(lines), "unclosed fenced code block"))
    if h1_count != 1:
        violations.append(Violation(path, 1, f"expected one H1, found {h1_count}"))

    for match in LINK_RE.finditer(text):
        target = _link_target(match.group(1))
        if target is None:
            continue
        if not (path.parent / target).resolve().exists():
            line_number = text.count("\n", 0, match.start()) + 1
            violations.append(
                Violation(path, line_number, f"linked file does not exist: {target}")
            )

    return violations


def _audit_name(path: Path, docs_root: Path) -> list[Violation]:
    relative = path.relative_to(docs_root)
    if relative == Path("README.md"):
        return []
    if path.name.startswith("README"):
        return [Violation(path, 1, "only docs/README.md may use the README name")]

    category = relative.parts[0]
    pattern = SLUG_RE
    message = "filename must use lowercase kebab-case"
    if category == "assessments":
        pattern = ASSESSMENT_RE
        message = "assessment filename must use YYYY-MM-DD-<topic>.md"
    elif category == "legacy":
        pattern = LEGACY_RE
        message = "legacy filename must use <topic>-legacy.md"
    if pattern.fullmatch(path.name):
        return []
    return [Violation(path, 1, message)]


def _audit_assessment_metadata(path: Path) -> list[Violation]:
    header = path.read_text(encoding="utf-8").splitlines()[:12]
    violations: list[Violation] = []
    for key in ASSESSMENT_METADATA:
        if not any(line.startswith(f"> {key}：") for line in header):
            violations.append(
                Violation(path, 1, f"assessment header is missing {key} metadata")
            )
    return violations


def audit_docs(docs_root: Path = DEFAULT_DOCS_ROOT) -> list[Violation]:
    docs_root = docs_root.resolve()
    index_path = docs_root / "README.md"
    if not index_path.is_file():
        return [Violation(index_path, 1, "central docs index does not exist")]

    files = sorted(docs_root.rglob("*.md"))
    index_text = index_path.read_text(encoding="utf-8")
    index_targets = {
        target
        for match in LINK_RE.finditer(index_text)
        if (target := _link_target(match.group(1))) is not None
    }
    violations: list[Violation] = []

    for path in files:
        violations.extend(_audit_name(path, docs_root))
        violations.extend(_audit_markdown(path))
        relative = path.relative_to(docs_root).as_posix()
        if path != index_path and relative not in index_targets:
            violations.append(
                Violation(path, 1, "document is missing from docs/README.md")
            )
        if path.parent == docs_root / "assessments":
            violations.extend(_audit_assessment_metadata(path))

    return violations


def main(argv: list[str]) -> int:
    docs_root = Path(argv[0]) if argv else DEFAULT_DOCS_ROOT
    violations = audit_docs(docs_root)
    if not violations:
        file_count = len(list(docs_root.rglob("*.md")))
        print(f"Docs validation passed ({file_count} files).")
        return 0

    print("Docs validation failed:")
    for violation in violations:
        print(violation.format())
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
