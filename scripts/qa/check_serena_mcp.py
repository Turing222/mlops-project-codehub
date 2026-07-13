#!/usr/bin/env python3
"""Smoke-test Serena MCP against fixed non-empty Python and TypeScript files.

职责：通过 stdio MCP 调用验证两个客户端 context 的符号索引；边界：不修改仓库文件，不替代 skill/MCP 静态契约校验；副作用：Serena 可更新被忽略的本地缓存和日志。
"""

from __future__ import annotations

import json
import selectors
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, cast

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = PROJECT_ROOT / "scripts" / "dev" / "serena-mcp.sh"
DEFAULT_CLIENTS = ("codex", "claude-code")
FIXED_SOURCE_FILES = (
    ("python", "scripts/qa/check_skills.py"),
    ("typescript", "frontend/apps/admin/src/stores/auth-store.ts"),
)
PROTOCOL_VERSION = "2025-06-18"
RESPONSE_TIMEOUT_SECONDS = 60.0
SHUTDOWN_TIMEOUT_SECONDS = 5.0


class SmokeCheckError(RuntimeError):
    """Raised when Serena cannot return a non-empty symbol overview."""


def _send_message(
    server_process: subprocess.Popen[str], message: dict[str, object]
) -> None:
    if server_process.stdin is None:
        raise SmokeCheckError("Serena stdin is unavailable")
    server_process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    server_process.stdin.flush()


def _read_response(
    server_process: subprocess.Popen[str], request_id: int
) -> dict[str, object]:
    if server_process.stdout is None:
        raise SmokeCheckError("Serena stdout is unavailable")
    selector = selectors.DefaultSelector()
    selector.register(server_process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + RESPONSE_TIMEOUT_SECONDS
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise SmokeCheckError(
                    f"timed out waiting for MCP response {request_id}"
                )
            line = server_process.stdout.readline()
            if not line:
                raise SmokeCheckError(f"Serena exited before MCP response {request_id}")
            try:
                message = json.loads(line)
            except json.JSONDecodeError as error:
                raise SmokeCheckError(f"invalid MCP JSON: {error.msg}") from error
            if isinstance(message, dict) and message.get("id") == request_id:
                return cast(dict[str, object], message)
    finally:
        selector.close()


def _extract_overview(
    response: dict[str, object], relative_path: str
) -> dict[str, object]:
    if "error" in response:
        raise SmokeCheckError(f"{relative_path}: MCP error: {response['error']}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise SmokeCheckError(f"{relative_path}: missing MCP result")
    structured = result.get("structuredContent")
    overview_text: object | None = None
    if isinstance(structured, dict):
        overview_text = structured.get("result")
    if not isinstance(overview_text, str):
        content = result.get("content")
        if isinstance(content, list):
            overview_text = next(
                (
                    item.get("text")
                    for item in content
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                ),
                None,
            )
    if not isinstance(overview_text, str):
        raise SmokeCheckError(f"{relative_path}: missing overview text")
    try:
        overview = json.loads(overview_text)
    except json.JSONDecodeError as error:
        raise SmokeCheckError(
            f"{relative_path}: overview is not JSON: {overview_text[:160]}"
        ) from error
    if not isinstance(overview, dict) or not overview:
        raise SmokeCheckError(f"{relative_path}: symbol overview is empty")
    return cast(dict[str, object], overview)


def _stderr_tail(stderr_log: IO[str]) -> str:
    stderr_log.flush()
    stderr_log.seek(0)
    return "".join(stderr_log.readlines()[-20:]).strip()


def _stop_server(server_process: subprocess.Popen[str]) -> None:
    if server_process.stdin is not None and not server_process.stdin.closed:
        server_process.stdin.close()
    try:
        server_process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        server_process.terminate()
        try:
            server_process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)


def _run_client(client: str) -> None:
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_log:
        server_process = subprocess.Popen(
            ["bash", str(SERVER_SCRIPT), client],
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_log,
            text=True,
            bufsize=1,
        )
        failure: Exception | None = None
        try:
            _send_message(
                server_process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "dewflow-serena-smoke",
                            "version": "1.0",
                        },
                    },
                },
            )
            initialize_response = _read_response(server_process, 1)
            if "error" in initialize_response:
                raise SmokeCheckError(
                    f"initialize failed: {initialize_response['error']}"
                )
            _send_message(
                server_process,
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
            )
            for request_id, (_, relative_path) in enumerate(
                FIXED_SOURCE_FILES, start=2
            ):
                _send_message(
                    server_process,
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {
                            "name": "get_symbols_overview",
                            "arguments": {
                                "relative_path": relative_path,
                                "depth": 0,
                                "max_answer_chars": 20000,
                            },
                        },
                    },
                )
                response = _read_response(server_process, request_id)
                _extract_overview(response, relative_path)
        except Exception as error:  # noqa: BLE001 - enrich all subprocess failures
            failure = error
        finally:
            _stop_server(server_process)

        if failure is not None:
            log_tail = _stderr_tail(stderr_log)
            detail = f"\nSerena log tail:\n{log_tail}" if log_tail else ""
            raise SmokeCheckError(f"{client}: {failure}{detail}") from failure
        if server_process.returncode != 0:
            log_tail = _stderr_tail(stderr_log)
            raise SmokeCheckError(
                f"{client}: Serena exited with {server_process.returncode}\n{log_tail}"
            )


def main(argv: list[str]) -> int:
    clients = tuple(argv) if argv else DEFAULT_CLIENTS
    invalid_clients = sorted(set(clients) - set(DEFAULT_CLIENTS))
    if invalid_clients:
        print(
            f"unsupported Serena clients: {', '.join(invalid_clients)}",
            file=sys.stderr,
        )
        return 2
    try:
        for client in clients:
            _run_client(client)
    except (OSError, SmokeCheckError) as error:
        print(f"Serena MCP smoke check failed: {error}", file=sys.stderr)
        return 1

    languages = ", ".join(language for language, _ in FIXED_SOURCE_FILES)
    print(f"Serena MCP smoke check passed for {', '.join(clients)} ({languages}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
