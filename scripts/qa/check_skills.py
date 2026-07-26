#!/usr/bin/env python3
"""Validate local Codex skill structure and references.

职责：校验 skill 结构、路由清单、Markdown 引用、Make target 和 Serena allowlist；边界：仅检查确定性仓库契约，不判断指令语义质量；副作用：只读扫描并通过退出码报告结果。
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import unquote

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = PROJECT_ROOT / ".codex" / "skills"
MAKEFILE_PATH = PROJECT_ROOT / "Makefile"
SKILL_INDEX_SPECS = (
    (PROJECT_ROOT / "AGENTS.md", "Local Skills"),
    (PROJECT_ROOT / "CLAUDE.md", "Task Skills"),
)
SERENA_PROJECT_PATH = PROJECT_ROOT / ".serena" / "project.yml"
CODEX_CONFIG_PATH = PROJECT_ROOT / ".codex" / "config.toml"
CLAUDE_SETTINGS_PATH = PROJECT_ROOT / ".claude" / "settings.json"

SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MAKE_COMMAND_RE = re.compile(r"(?<![\w-])make\s+([A-Za-z0-9_.%*-]+)")
MAKE_TARGET_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9_.-]*(?:\s+[A-Za-z0-9][A-Za-z0-9_.-]*)*):(?:\s|$)"
)
REQUIRED_SKILL_FIELDS = ("name", "description")
REQUIRED_INTERFACE_FIELDS = ("display_name", "short_description", "default_prompt")
SKILL_INDEX_RE = re.compile(r"\.codex/skills/([a-z0-9]+(?:-[a-z0-9]+)*)/SKILL\.md")
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
SERENA_TOOL_PREFIX = "mcp__serena__"


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


def _find_assignment_line(text: str, key: str) -> int:
    pattern = re.compile(rf'^\s*["\']?{re.escape(key)}["\']?\s*[:=]')
    for line_number, line in enumerate(text.splitlines(), start=1):
        if pattern.match(line):
            return line_number
    return 1


def _load_toml_mapping(
    path: Path, text: str
) -> tuple[dict[str, object] | None, list[Violation]]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return None, [
            Violation(
                path=path,
                line=getattr(error, "lineno", 1),
                message=f"invalid TOML: {error}",
            )
        ]
    return cast(dict[str, object], data), []


def _load_json_mapping(
    path: Path, text: str
) -> tuple[dict[str, object] | None, list[Violation]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return None, [
            Violation(
                path=path, line=error.lineno, message=f"invalid JSON: {error.msg}"
            )
        ]
    if not isinstance(data, dict):
        return None, [Violation(path, 1, "JSON document must be a mapping")]
    return cast(dict[str, object], data), []


def _nested_value(data: dict[str, object], keys: tuple[str, ...]) -> object | None:
    value: object = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        mapping = cast(dict[str, object], value)
        value = mapping.get(key)
    return value


def _string_list(
    path: Path, text: str, key: str, value: object
) -> tuple[set[str] | None, list[Violation]]:
    line = _find_assignment_line(text, key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None, [Violation(path, line, f"`{key}` must be a list of strings")]
    items = cast(list[str], value)
    if len(items) != len(set(items)):
        return set(items), [Violation(path, line, f"`{key}` contains duplicate tools")]
    return set(items), []


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


def audit_skill_indexes(
    skills_root: Path = SKILLS_ROOT,
    index_specs: tuple[tuple[Path, str], ...] = SKILL_INDEX_SPECS,
) -> list[Violation]:
    if not skills_root.is_dir():
        raise FileNotFoundError(f"skills directory does not exist: {skills_root}")

    skill_names = {path.name for path in skills_root.iterdir() if path.is_dir()}
    violations: list[Violation] = []
    for index_path, section_title in index_specs:
        text = index_path.read_text(encoding="utf-8")
        section_span = _markdown_section_span(text, section_title)
        if section_span is None:
            violations.append(
                Violation(
                    index_path,
                    1,
                    f"skill index section `{section_title}` does not exist",
                )
            )
            continue

        section_start, section_end = section_span
        section_text = text[section_start:section_end]
        indexed_lines: dict[str, int] = {}
        for match in SKILL_INDEX_RE.finditer(section_text):
            skill_name = match.group(1)
            match_start = section_start + match.start()
            line = text.count("\n", 0, match_start) + 1
            if skill_name in indexed_lines:
                violations.append(
                    Violation(
                        index_path,
                        line,
                        f"skill index lists `{skill_name}` more than once",
                    )
                )
                continue
            indexed_lines[skill_name] = line

        indexed_names = set(indexed_lines)
        for skill_name in sorted(skill_names - indexed_names):
            violations.append(
                Violation(
                    index_path,
                    1,
                    f"skill index is missing `{skill_name}`",
                )
            )
        for skill_name in sorted(indexed_names - skill_names):
            violations.append(
                Violation(
                    index_path,
                    indexed_lines[skill_name],
                    f"skill index references unknown skill `{skill_name}`",
                )
            )
    return violations


def _tool_list_difference(expected: set[str], actual: set[str]) -> str:
    parts: list[str] = []
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        parts.append(f"missing={missing}")
    if extra:
        parts.append(f"extra={extra}")
    return ", ".join(parts)


def _markdown_section_span(text: str, title: str) -> tuple[int, int] | None:
    headings = list(MARKDOWN_HEADING_RE.finditer(text))
    for index, heading in enumerate(headings):
        if heading.group(2) != title:
            continue

        level = len(heading.group(1))
        section_end = len(text)
        for following_heading in headings[index + 1 :]:
            if len(following_heading.group(1)) <= level:
                section_end = following_heading.start()
                break
        return heading.end(), section_end
    return None


def audit_mcp_allowlists(
    serena_project_path: Path = SERENA_PROJECT_PATH,
    codex_config_path: Path = CODEX_CONFIG_PATH,
    claude_settings_path: Path = CLAUDE_SETTINGS_PATH,
) -> list[Violation]:
    serena_text = serena_project_path.read_text(encoding="utf-8")
    codex_text = codex_config_path.read_text(encoding="utf-8")
    claude_text = claude_settings_path.read_text(encoding="utf-8")

    serena_data, violations = _load_yaml_mapping(serena_project_path, serena_text)
    codex_data, codex_violations = _load_toml_mapping(codex_config_path, codex_text)
    claude_data, claude_violations = _load_json_mapping(
        claude_settings_path, claude_text
    )
    violations.extend(codex_violations)
    violations.extend(claude_violations)
    if serena_data is None or codex_data is None or claude_data is None:
        return violations

    fixed_tools, list_violations = _string_list(
        serena_project_path,
        serena_text,
        "fixed_tools",
        serena_data.get("fixed_tools"),
    )
    violations.extend(list_violations)
    if fixed_tools == set():
        violations.append(
            Violation(
                serena_project_path,
                _find_assignment_line(serena_text, "fixed_tools"),
                "`fixed_tools` must not be empty",
            )
        )
        return violations
    enabled_tools, list_violations = _string_list(
        codex_config_path,
        codex_text,
        "enabled_tools",
        _nested_value(codex_data, ("mcp_servers", "serena", "enabled_tools")),
    )
    violations.extend(list_violations)
    claude_allow, list_violations = _string_list(
        claude_settings_path,
        claude_text,
        "allow",
        _nested_value(claude_data, ("permissions", "allow")),
    )
    violations.extend(list_violations)
    if fixed_tools is None or enabled_tools is None or claude_allow is None:
        return violations

    claude_tools = {
        item.removeprefix(SERENA_TOOL_PREFIX)
        for item in claude_allow
        if item.startswith(SERENA_TOOL_PREFIX)
    }
    for path, text, key, actual in (
        (codex_config_path, codex_text, "enabled_tools", enabled_tools),
        (claude_settings_path, claude_text, "allow", claude_tools),
    ):
        if actual != fixed_tools:
            difference = _tool_list_difference(fixed_tools, actual)
            violations.append(
                Violation(
                    path,
                    _find_assignment_line(text, key),
                    f"Serena allowlist differs from `fixed_tools`: {difference}",
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
        violations.extend(audit_skill_indexes())
        violations.extend(audit_mcp_allowlists())
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
