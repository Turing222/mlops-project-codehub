"""Import boundaries unit tests.

职责：验证 web 层不直接 import langfuse SDK；边界：静态扫描源码树；副作用：无。
"""

import re
from pathlib import Path

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+(\S+)", re.MULTILINE)

# Web-facing directories that should only use langfuse_utils wrapper.
_FORBIDDEN_DIRS = [
    "backend/api",
    "backend/middleware",
    "backend/services",
    "backend/application/chat",
]


def _collect_py_files() -> list[Path]:
    root = Path()
    result: list[Path] = []
    for dir_path in _FORBIDDEN_DIRS:
        base = root / dir_path
        if not base.is_dir():
            continue
        for py_file in base.rglob("*.py"):
            result.append(py_file)
    return sorted(result)


def test_web_no_langfuse_sdk_import():
    for filepath in _collect_py_files():
        content = filepath.read_text()
        for match in _IMPORT_RE.finditer(content):
            module = match.group(1)
            assert not module.startswith("langfuse"), (
                f"{filepath} directly imports langfuse SDK: {module}"
            )
