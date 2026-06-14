"""Test environment helpers for pytest profiles and dependency gates.

职责：集中读取测试 profile 和 TEST_* 覆盖值；边界：只供测试与 fixture 使用；副作用：缺少必需环境变量时跳过当前测试。
"""

from __future__ import annotations

import importlib
import os
from typing import Literal, cast

import pytest

TestProfile = Literal["unit", "local", "ci", "external"]

DEFAULT_TEST_PROFILE: TestProfile = "local"
VALID_TEST_PROFILES: frozenset[str] = frozenset({"unit", "local", "ci", "external"})
REQUIRED_ENV_BY_MARKER: dict[str, str] = {
    "requires_db": "TEST_DATABASE_URL",
    "requires_redis": "TEST_REDIS_URL",
    "requires_taskiq": "TEST_TASKIQ_REDIS_URL",
    "requires_s3": "TEST_S3_ENDPOINT_URL",
    "requires_llm": "TEST_LLM_API_KEY",
}

# Markers whose tests need certain Python packages importable at collection time.
REQUIRED_PKG_BY_MARKER: dict[str, list[str]] = {
    "requires_taskiq": ["taskiq", "taskiq_redis"],
    "requires_ai": ["openai"],
}


def get_test_profile() -> TestProfile:
    profile = os.getenv("DEWFLOW_TEST_PROFILE", DEFAULT_TEST_PROFILE).strip().lower()
    if profile not in VALID_TEST_PROFILES:
        message = (
            "Invalid DEWFLOW_TEST_PROFILE="
            f"{profile!r}; expected one of {sorted(VALID_TEST_PROFILES)}"
        )
        raise pytest.UsageError(message)
    return cast(TestProfile, profile)


def optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value


def require_env(name: str) -> str:
    value = optional_env(name)
    if value is None:
        pytest.skip(f"{name} is required for this test")
    return value


def pkg_available(name: str) -> bool:
    try:
        importlib.import_module(name)
    except ImportError:
        return False
    return True


def pkgs_available_for_marker(marker_name: str) -> bool:
    for pkg in REQUIRED_PKG_BY_MARKER.get(marker_name, ()):
        if not pkg_available(pkg):
            return False
    return True
