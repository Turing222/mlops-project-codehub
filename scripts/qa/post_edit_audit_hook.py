#!/usr/bin/env python3
"""PostToolUse hook adapter for fast standards checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from check_claude_fast import audit_paths


def _extract_file_path(payload: dict) -> str | None:
    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    file_path = tool_input.get("file_path") or tool_response.get("filePath")
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    return file_path


def main() -> int:
    payload = json.load(sys.stdin)
    file_path = _extract_file_path(payload)
    if file_path is None:
        return 0

    path = Path(file_path)
    violations = audit_paths([path])
    if not violations:
        return 0

    violation_text = "\n".join(f"- {violation.format()}" for violation in violations)
    response = {
        "decision": "block",
        "reason": f"Project standards audit failed for {path}",
        "systemMessage": f"Project standards audit failed for {path.name}",
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"Project standards audit failed for {path}:\n{violation_text}\n"
                "Fix the file so it matches the documented project standards before continuing."
            ),
        },
    }
    json.dump(response, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
