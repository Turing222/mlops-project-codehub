"""Serena MCP smoke-check unit tests.

职责：覆盖符号响应解析和空文件防护；边界：不启动真实 Serena 或语言服务器；副作用：无。
"""

import json

import pytest

from scripts.qa.check_serena_mcp import SmokeCheckError, _extract_overview


def _response(overview: object) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "content": [{"type": "text", "text": json.dumps(overview)}],
            "structuredContent": {"result": json.dumps(overview)},
            "isError": False,
        },
    }


def test_extract_overview_accepts_non_empty_symbols() -> None:
    response = _response({"Function": ["main"]})

    overview = _extract_overview(response, "scripts/qa/check_skills.py")

    assert overview == {"Function": ["main"]}


def test_extract_overview_rejects_empty_symbol_map() -> None:
    with pytest.raises(SmokeCheckError, match="symbol overview is empty"):
        _extract_overview(_response({}), "evals/__init__.py")


def test_extract_overview_rejects_non_json_tool_error() -> None:
    response: dict[str, object] = {
        "result": {
            "content": [{"type": "text", "text": "Error: tool is not active"}],
            "isError": False,
        }
    }

    with pytest.raises(SmokeCheckError, match="overview is not JSON"):
        _extract_overview(response, "backend/main.py")
