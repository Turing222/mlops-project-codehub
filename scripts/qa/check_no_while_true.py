"""Reject bare while True loops in Python source files."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

DEFAULT_TARGETS = (
    Path("backend"),
    Path("scripts"),
    Path("tests"),
    Path(".codex/skills"),
)
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "alembic/versions",
    "data",
    "logs",
    "node_modules",
    "postgres_data",
    "venv",
}


def is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & EXCLUDED_DIRS) or str(path).startswith("alembic/versions/")


def iter_python_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if not path.exists() or is_excluded(path):
            continue
        if path.is_file():
            if path.suffix == ".py":
                files.append(path)
            continue
        files.extend(
            child
            for child in path.rglob("*.py")
            if child.is_file() and not is_excluded(child)
        )
    return sorted(files)


def has_bare_while_true(node: ast.While) -> bool:
    return isinstance(node.test, ast.Constant) and node.test.value is True


def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv] if argv else list(DEFAULT_TARGETS)
    violations: list[tuple[Path, int, int]] = []

    for path in iter_python_files(paths):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            print(f"{path}:{exc.lineno}: syntax error: {exc.msg}", file=sys.stderr)
            return 2

        for node in ast.walk(tree):
            if isinstance(node, ast.While) and has_bare_while_true(node):
                violations.append((path, node.lineno, node.col_offset + 1))

    if violations:
        print("Bare `while True` loops are forbidden. Use a bounded loop instead.")
        for path, lineno, col in violations:
            print(f"{path}:{lineno}:{col}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
