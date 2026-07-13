"""Documentation contract validation unit tests.

职责：覆盖 docs 命名、中央索引、链接和 Markdown 布局；边界：仅使用临时目录；副作用：写入 pytest 临时文件。
"""

from pathlib import Path

from scripts.qa.check_docs import audit_docs


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _assessment() -> str:
    return """# Documentation Audit

> 日期：2026-07-13
> 范围：temporary docs tree
> 性质：unit-test fixture
> 证据基线：generated files
> 状态：冻结

## Result

Valid.
"""


def _build_valid_tree(tmp_path: Path) -> Path:
    docs_root = tmp_path / "docs"
    _write(
        docs_root / "README.md",
        """# Project Docs

- [Guide](guide.md)
- [Audit](assessments/2026-07-13-documentation-audit.md)
""",
    )
    _write(docs_root / "guide.md", "# Guide\n\nValid.\n")
    _write(
        docs_root / "assessments" / "2026-07-13-documentation-audit.md",
        _assessment(),
    )
    return docs_root


def test_audit_docs_accepts_valid_documentation_tree(tmp_path: Path) -> None:
    docs_root = _build_valid_tree(tmp_path)

    assert audit_docs(docs_root) == []


def test_audit_docs_reports_name_index_and_link_violations(tmp_path: Path) -> None:
    docs_root = _build_valid_tree(tmp_path)
    _write(docs_root / "Bad_Name.md", "# Bad Name\n\n[Missing](missing.md)\n")

    messages = {violation.message for violation in audit_docs(docs_root)}

    assert "filename must use lowercase kebab-case" in messages
    assert "document is missing from docs/README.md" in messages
    assert "linked file does not exist: missing.md" in messages


def test_audit_docs_reports_markdown_layout_violations(tmp_path: Path) -> None:
    docs_root = _build_valid_tree(tmp_path)
    _write(
        docs_root / "guide.md",
        """# Guide

# Duplicate

| Column |
|---|

```
output
```

"""
        "Trailing. \n",
    )

    messages = {violation.message for violation in audit_docs(docs_root)}

    assert "expected one H1, found 2" in messages
    assert "fenced code block needs a language" in messages
    assert "table separator must use spaced ---" in messages
    assert "trailing whitespace" in messages


def test_audit_docs_requires_assessment_metadata(tmp_path: Path) -> None:
    docs_root = _build_valid_tree(tmp_path)
    assessment_path = docs_root / "assessments" / "2026-07-13-documentation-audit.md"
    _write(assessment_path, "# Documentation Audit\n")

    messages = {violation.message for violation in audit_docs(docs_root)}

    for key in ("日期", "范围", "性质", "证据基线", "状态"):
        assert f"assessment header is missing {key} metadata" in messages
