#!/usr/bin/env python3
"""Validate local Codex skill structure and references.

职责：校验 skill frontmatter、agent metadata、Markdown 链接和 Make target；边界：仅检查确定性仓库契约，不判断指令语义质量；副作用：只读扫描并通过退出码报告结果。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import unquote

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / ".codex" / "skills"
MAKEFILE_PATH = PROJECT_ROOT / "Makefile"

SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MAKE_COMMAND_RE = re.compile(r"(?<![\w-])make\s+([A-Za-z0-9_.%*-]+)")
MAKE_TARGET_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9_.-]*(?:\s+[A-Za-z0-9][A-Za-z0-9_.-]*)*):(?:\s|$)"
)
REQUIRED_SKILL_FIELDS = ("name", "description")
REQUIRED_INTERFACE_FIELDS = ("display_name", "short_description", "default_prompt")


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def _yaml_error_line(error: yaml.YAMLError, offset: int = 0) -> int:
    problem_mark = getattr(error, "problem_mark", None)
    if problem_mark is None:
        return 1 + offset
    return problem_mark.line + 1 + offset


def _find_key_line(text: str, key: str, start_line: int = 1) -> int:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    for line_number, line in enumerate(text.splitlines(), start=start_line):
        if pattern.match(line):
            return line_number
    return start_line


def _load_yaml_mapping(
    path: Path,
    text: str,
    *,
    line_offset: int = 0,
) -> tuple[dict[str, object] | None, list[Violation]]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return None, [
            Violation(
                path=path,
                line=_yaml_error_line(error, line_offset),
                message=f"invalid YAML: {getattr(error, 'problem', None) or 'parse error'}",
            )
        ]

    if not isinstance(data, dict):
        return None, [
            Violation(
                path=path,
                line=1 + line_offset,
                message="YAML document must be a mapping",
            )
        ]
    return data, []


def _extract_frontmatter(path: Path, text: str) -> tuple[str | None, list[Violation]]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None, [
            Violation(
                path=path, line=1, message="SKILL.md must start with YAML frontmatter"
            )
        ]

    try:
        closing_index = lines[1:].index("---") + 1
    except ValueError:
        return None, [
            Violation(path=path, line=1, message="SKILL.md frontmatter is not closed")
        ]

    return "\n".join(lines[1:closing_index]), []


def _validate_skill_frontmatter(skill_dir: Path, skill_path: Path) -> list[Violation]:
    text = skill_path.read_text(encoding="utf-8")
    frontmatter, violations = _extract_frontmatter(skill_path, text)
    if frontmatter is None:
        return violations

    data, yaml_violations = _load_yaml_mapping(
        skill_path,
        frontmatter,
        line_offset=1,
    )
    violations.extend(yaml_violations)
    if data is None:
        return violations

    for field in REQUIRED_SKILL_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            violations.append(
                Violation(
                    path=skill_path,
                    line=_find_key_line(frontmatter, field, start_line=2),
                    message=f"required frontmatter field `{field}` must be a non-empty string",
                )
            )

    name = data.get("name")
    if isinstance(name, str) and name.strip():
        name_line = _find_key_line(frontmatter, "name", start_line=2)
        if not SKILL_NAME_RE.fullmatch(name):
            violations.append(
                Violation(
                    path=skill_path,
                    line=name_line,
                    message="frontmatter `name` must use kebab-case",
                )
            )
        if name != skill_dir.name:
            violations.append(
                Violation(
                    path=skill_path,
                    line=name_line,
                    message=(
                        f"frontmatter `name` must match skill directory `{skill_dir.name}`"
                    ),
                )
            )
    return violations


def _validate_agent_metadata(skill_dir: Path) -> list[Violation]:
    metadata_path = skill_dir / "agents" / "openai.yaml"
    if not metadata_path.exists():
        return []

    text = metadata_path.read_text(encoding="utf-8")
    data, violations = _load_yaml_mapping(metadata_path, text)
    if data is None:
        return violations

    interface = data.get("interface")
    if not isinstance(interface, dict):
        violations.append(
            Violation(
                path=metadata_path,
                line=_find_key_line(text, "interface"),
                message="`interface` must be a mapping",
            )
        )
        return violations

    interface_data = cast(dict[str, object], interface)
    for field in REQUIRED_INTERFACE_FIELDS:
        value = interface_data.get(field)
        if not isinstance(value, str) or not value.strip():
            violations.append(
                Violation(
                    path=metadata_path,
                    line=_find_key_line(text, field),
                    message=f"`interface.{field}` must be a non-empty string",
                )
            )
    return violations


def _markdown_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def _validate_markdown_links(path: Path) -> list[Violation]:
    text = path.read_text(encoding="utf-8")
    violations: list[Violation] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = _markdown_target(match.group(1))
        if (
            not target
            or target.startswith(("#", "/", "mailto:", "data:"))
            or "://" in target
        ):
            continue

        local_target = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if local_target and not (path.parent / local_target).resolve().exists():
            violations.append(
                Violation(
                    path=path,
                    line=text.count("\n", 0, match.start()) + 1,
                    message=f"linked file does not exist: {target}",
                )
            )
    return violations


def _load_make_targets(makefile_path: Path) -> set[str]:
    targets: set[str] = set()
    for line in makefile_path.read_text(encoding="utf-8").splitlines():
        match = MAKE_TARGET_RE.match(line)
        if match:
            targets.update(match.group(1).split())
    return targets


def _validate_make_targets(path: Path, make_targets: set[str]) -> list[Violation]:
    text = path.read_text(encoding="utf-8")
    violations: list[Violation] = []
    for match in MAKE_COMMAND_RE.finditer(text):
        target = match.group(1)
        if "*" in target or "%" in target or target in make_targets:
            continue
        violations.append(
            Violation(
                path=path,
                line=text.count("\n", 0, match.start()) + 1,
                message=f"referenced Make target does not exist: {target}",
            )
        )
    return violations


def audit_skills(
    skills_root: Path = SKILLS_ROOT,
    makefile_path: Path = MAKEFILE_PATH,
) -> list[Violation]:
    if not skills_root.is_dir():
        raise FileNotFoundError(f"skills directory does not exist: {skills_root}")
    if not makefile_path.is_file():
        raise FileNotFoundError(f"Makefile does not exist: {makefile_path}")

    make_targets = _load_make_targets(makefile_path)
    violations: list[Violation] = []

    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            violations.append(
                Violation(
                    path=skill_path,
                    line=1,
                    message="skill directory must contain SKILL.md",
                )
            )
            continue

        violations.extend(_validate_skill_frontmatter(skill_dir, skill_path))
        violations.extend(_validate_agent_metadata(skill_dir))

        markdown_paths = [skill_path]
        references_dir = skill_dir / "references"
        if references_dir.is_dir():
            markdown_paths.extend(sorted(references_dir.rglob("*.md")))

        for markdown_path in markdown_paths:
            violations.extend(_validate_markdown_links(markdown_path))
            violations.extend(_validate_make_targets(markdown_path, make_targets))

    return violations


def main() -> int:
    try:
        violations = audit_skills()
    except (OSError, UnicodeError) as error:
        print(f"Skill validation could not run: {error}", file=sys.stderr)
        return 2

    if not violations:
        print("Skill validation passed.")
        return 0

    print("Skill validation failed:")
    for violation in violations:
        try:
            display_path = violation.path.relative_to(PROJECT_ROOT)
        except ValueError:
            display_path = violation.path
        print(f"- {display_path}:{violation.line}: {violation.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
