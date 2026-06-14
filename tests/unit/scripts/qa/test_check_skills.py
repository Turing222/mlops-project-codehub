"""Test deterministic validation of local Codex skill contracts.

职责：覆盖 skill frontmatter、agent metadata、Markdown 引用和 Make target 校验；边界：仅使用临时目录，不读取或修改真实 skill；副作用：写入 pytest 临时文件。
"""

from pathlib import Path

from scripts.qa.check_skills import audit_skills


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
