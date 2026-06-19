"""Logger configuration unit tests.

职责：验证日志级别解析；边界：纯函数，无 I/O；副作用：无。
"""

import logging

from backend.observability.logger import _resolve_log_level


def test_resolve_log_level_defaults_to_info() -> None:
    assert _resolve_log_level(None) == logging.INFO
    assert _resolve_log_level("") == logging.INFO


def test_resolve_log_level_accepts_common_names() -> None:
    assert _resolve_log_level("debug") == logging.DEBUG
    assert _resolve_log_level("INFO") == logging.INFO
    assert _resolve_log_level("warn") == logging.WARNING
    assert _resolve_log_level("warning") == logging.WARNING
    assert _resolve_log_level("error") == logging.ERROR


def test_resolve_log_level_invalid_value_falls_back_to_info() -> None:
    assert _resolve_log_level("chatty") == logging.INFO
