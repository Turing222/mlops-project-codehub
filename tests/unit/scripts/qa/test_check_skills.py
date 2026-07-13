"""Codex skill contract validation unit tests.

职责：覆盖 skill 结构、路由清单、Markdown 引用、Make target 和 Serena allowlist 校验；边界：仅使用临时目录，不读取或修改真实 skill；副作用：写入 pytest 临时文件。
"""

import json
from pathlib import Path

from scripts.qa.check_skills import (
    audit_mcp_allowlists,
    audit_skill_indexes,
    audit_skills,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _valid_skill(name: str = "demo-skill") -> str:
    return f"""---
name: {name}
description: Validate a demo skill.
---

# Demo Skill

Read [details](references/details.md) and run `make qa-demo`.
"""


def _valid_metadata() -> str:
    return """interface:
  display_name: "Demo Skill"
  short_description: "Validate a demo skill"
  default_prompt: "Validate the demo skill."
"""


def _makefile() -> str:
    return """qa-demo:
\t@true
"""


def _build_valid_tree(tmp_path: Path) -> tuple[Path, Path]:
    skills_root = tmp_path / ".codex" / "skills"
    skill_dir = skills_root / "demo-skill"
    _write(skill_dir / "SKILL.md", _valid_skill())
    _write(skill_dir / "references" / "details.md", "# Details\n")
    _write(skill_dir / "agents" / "openai.yaml", _valid_metadata())
    makefile_path = tmp_path / "Makefile"
    _write(makefile_path, _makefile())
    return skills_root, makefile_path


def _skill_index(section_title: str, *skill_names: str) -> str:
    entries = "\n".join(
        f"- `.codex/skills/{skill_name}/SKILL.md`" for skill_name in skill_names
    )
    return f"# Routing\n\n## {section_title}\n\n{entries}\n"


def _build_mcp_configs(
    tmp_path: Path,
    *,
    fixed_tools: tuple[str, ...] = ("find_symbol", "initial_instructions"),
    codex_tools: tuple[str, ...] | None = None,
    claude_tools: tuple[str, ...] | None = None,
) -> tuple[Path, Path, Path]:
    codex_tools = fixed_tools if codex_tools is None else codex_tools
    claude_tools = fixed_tools if claude_tools is None else claude_tools
    serena_project_path = tmp_path / ".serena" / "project.yml"
    codex_config_path = tmp_path / ".codex" / "config.toml"
    claude_settings_path = tmp_path / ".claude" / "settings.json"
    _write(
        serena_project_path,
        (
            "fixed_tools: []\n"
            if not fixed_tools
            else "fixed_tools:\n" + "".join(f"- {tool}\n" for tool in fixed_tools)
        ),
    )
    _write(
        codex_config_path,
        "[mcp_servers.serena]\n"
        "enabled_tools = [" + ", ".join(f'"{tool}"' for tool in codex_tools) + "]\n",
    )
    _write(
        claude_settings_path,
        json.dumps(
            {
                "permissions": {
                    "allow": [
                        "Bash(make lint *)",
                        *(f"mcp__serena__{tool}" for tool in claude_tools),
                    ]
                }
            }
        ),
    )
    return serena_project_path, codex_config_path, claude_settings_path


def test_audit_skills_accepts_valid_skill(tmp_path: Path) -> None:
    skills_root, makefile_path = _build_valid_tree(tmp_path)

    assert audit_skills(skills_root, makefile_path) == []


def test_audit_skills_requires_skill_file(tmp_path: Path) -> None:
    skills_root = tmp_path / ".codex" / "skills"
    (skills_root / "missing-skill").mkdir(parents=True)
    makefile_path = tmp_path / "Makefile"
    _write(makefile_path, _makefile())

    violations = audit_skills(skills_root, makefile_path)

    assert [violation.message for violation in violations] == [
        "skill directory must contain SKILL.md"
    ]


def test_audit_skills_validates_frontmatter_contract(tmp_path: Path) -> None:
    skills_root, makefile_path = _build_valid_tree(tmp_path)
    _write(
        skills_root / "demo-skill" / "SKILL.md",
        """---
name: Wrong_Name
description:
---

# Demo Skill
""",
    )

    messages = {
        violation.message for violation in audit_skills(skills_root, makefile_path)
    }

    assert "frontmatter `name` must use kebab-case" in messages
    assert "frontmatter `name` must match skill directory `demo-skill`" in messages
    assert (
        "required frontmatter field `description` must be a non-empty string"
        in messages
    )


def test_audit_skills_reports_invalid_frontmatter_yaml(tmp_path: Path) -> None:
    skills_root, makefile_path = _build_valid_tree(tmp_path)
    _write(
        skills_root / "demo-skill" / "SKILL.md",
        """---
name: [demo-skill
description: Broken YAML.
---
""",
    )

    violations = audit_skills(skills_root, makefile_path)

    assert len(violations) == 1
    assert violations[0].message.startswith("invalid YAML:")


def test_audit_skills_validates_agent_metadata(tmp_path: Path) -> None:
    skills_root, makefile_path = _build_valid_tree(tmp_path)
    _write(
        skills_root / "demo-skill" / "agents" / "openai.yaml",
        """interface:
  display_name: ""
  short_description: "Demo"
""",
    )

    messages = {
        violation.message for violation in audit_skills(skills_root, makefile_path)
    }

    assert "`interface.display_name` must be a non-empty string" in messages
    assert "`interface.default_prompt` must be a non-empty string" in messages


def test_audit_skills_reports_broken_markdown_link(tmp_path: Path) -> None:
    skills_root, makefile_path = _build_valid_tree(tmp_path)
    _write(
        skills_root / "demo-skill" / "references" / "details.md",
        "Read [missing](missing.md).\n",
    )

    violations = audit_skills(skills_root, makefile_path)

    assert [violation.message for violation in violations] == [
        "linked file does not exist: missing.md"
    ]


def test_audit_skills_reports_unknown_make_target(tmp_path: Path) -> None:
    skills_root, makefile_path = _build_valid_tree(tmp_path)
    _write(
        skills_root / "demo-skill" / "references" / "details.md",
        "Run `make qa-missing`, but wildcard guidance such as `make qa-*` is allowed.\n",
    )

    violations = audit_skills(skills_root, makefile_path)

    assert [violation.message for violation in violations] == [
        "referenced Make target does not exist: qa-missing"
    ]


def test_audit_skill_indexes_accepts_matching_indexes(tmp_path: Path) -> None:
    skills_root, _ = _build_valid_tree(tmp_path)
    agents_path = tmp_path / "AGENTS.md"
    claude_path = tmp_path / "CLAUDE.md"
    _write(agents_path, _skill_index("Local Skills", "demo-skill"))
    _write(claude_path, _skill_index("Task Skills", "demo-skill"))

    violations = audit_skill_indexes(
        skills_root,
        ((agents_path, "Local Skills"), (claude_path, "Task Skills")),
    )

    assert violations == []


def test_audit_skill_indexes_reports_missing_and_unknown_skills(
    tmp_path: Path,
) -> None:
    skills_root, _ = _build_valid_tree(tmp_path)
    index_path = tmp_path / "AGENTS.md"
    _write(index_path, _skill_index("Local Skills", "unknown-skill"))

    messages = {
        violation.message
        for violation in audit_skill_indexes(
            skills_root, ((index_path, "Local Skills"),)
        )
    }

    assert messages == {
        "skill index is missing `demo-skill`",
        "skill index references unknown skill `unknown-skill`",
    }


def test_audit_skill_indexes_ignores_mentions_outside_inventory(
    tmp_path: Path,
) -> None:
    skills_root, _ = _build_valid_tree(tmp_path)
    index_path = tmp_path / "AGENTS.md"
    _write(
        index_path,
        "# Routing\n\n"
        "Load `.codex/skills/demo-skill/SKILL.md` before work.\n\n"
        "## Local Skills\n",
    )

    messages = [
        violation.message
        for violation in audit_skill_indexes(
            skills_root, ((index_path, "Local Skills"),)
        )
    ]

    assert messages == ["skill index is missing `demo-skill`"]


def test_audit_skill_indexes_requires_inventory_section(tmp_path: Path) -> None:
    skills_root, _ = _build_valid_tree(tmp_path)
    index_path = tmp_path / "AGENTS.md"
    _write(index_path, "# Routing\n")

    messages = [
        violation.message
        for violation in audit_skill_indexes(
            skills_root, ((index_path, "Local Skills"),)
        )
    ]

    assert messages == ["skill index section `Local Skills` does not exist"]


def test_audit_skill_indexes_reports_duplicate_entries(tmp_path: Path) -> None:
    skills_root, _ = _build_valid_tree(tmp_path)
    index_path = tmp_path / "AGENTS.md"
    _write(
        index_path,
        _skill_index("Local Skills", "demo-skill", "demo-skill"),
    )

    messages = [
        violation.message
        for violation in audit_skill_indexes(
            skills_root, ((index_path, "Local Skills"),)
        )
    ]

    assert messages == ["skill index lists `demo-skill` more than once"]


def test_audit_mcp_allowlists_accepts_matching_tool_sets(tmp_path: Path) -> None:
    config_paths = _build_mcp_configs(
        tmp_path,
        codex_tools=("initial_instructions", "find_symbol"),
        claude_tools=("find_symbol", "initial_instructions"),
    )

    assert audit_mcp_allowlists(*config_paths) == []


def test_audit_mcp_allowlists_reports_client_drift(tmp_path: Path) -> None:
    config_paths = _build_mcp_configs(
        tmp_path,
        codex_tools=("find_symbol", "extra_tool"),
        claude_tools=("find_symbol",),
    )

    messages = [violation.message for violation in audit_mcp_allowlists(*config_paths)]

    assert messages == [
        "Serena allowlist differs from `fixed_tools`: "
        "missing=['initial_instructions'], extra=['extra_tool']",
        "Serena allowlist differs from `fixed_tools`: missing=['initial_instructions']",
    ]


def test_audit_mcp_allowlists_reports_duplicate_tools(tmp_path: Path) -> None:
    config_paths = _build_mcp_configs(
        tmp_path,
        codex_tools=("find_symbol", "find_symbol", "initial_instructions"),
    )

    messages = [violation.message for violation in audit_mcp_allowlists(*config_paths)]

    assert messages == ["`enabled_tools` contains duplicate tools"]


def test_audit_mcp_allowlists_rejects_empty_fixed_tools(tmp_path: Path) -> None:
    config_paths = _build_mcp_configs(tmp_path, fixed_tools=())

    messages = [violation.message for violation in audit_mcp_allowlists(*config_paths)]

    assert messages == ["`fixed_tools` must not be empty"]


def test_audit_mcp_allowlists_reports_empty_client_allowlists(tmp_path: Path) -> None:
    config_paths = _build_mcp_configs(
        tmp_path,
        codex_tools=(),
        claude_tools=(),
    )

    messages = [violation.message for violation in audit_mcp_allowlists(*config_paths)]

    assert messages == [
        "Serena allowlist differs from `fixed_tools`: "
        "missing=['find_symbol', 'initial_instructions']",
        "Serena allowlist differs from `fixed_tools`: "
        "missing=['find_symbol', 'initial_instructions']",
    ]
