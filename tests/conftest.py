"""Global pytest fixtures and test-safe environment setup.

Keep this file lightweight and avoid importing FastAPI app here.
Fixtures that require app startup should live in tests/component or tests/integration.
"""

import os
from collections.abc import Iterator

import pytest

from tests.helpers.env import (
    REQUIRED_ENV_BY_MARKER,
    REQUIRED_PKG_BY_MARKER,
    get_test_profile,
    optional_env,
    pkgs_available_for_marker,
)


def pytest_configure() -> None:
    """Normalize env before test collection imports backend settings."""
    get_test_profile()
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-chars")
    os.environ.setdefault("AUTH_REGISTER_RATE_LIMIT_TIMES", "100000")
    os.environ.setdefault("AUTH_LOGIN_RATE_LIMIT_TIMES", "100000")
    os.environ.setdefault("BUSINESS_RATE_LIMIT_TIMES", "100000")
    os.environ.setdefault("CHAT_RATE_LIMIT_TIMES", "100000")


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip tests that need unavailable profile capabilities."""
    profile = get_test_profile()
    marker_names = {marker.name for marker in item.iter_markers()}

    if "local_only" in marker_names and profile == "ci":
        pytest.skip("local_only test is skipped in CI profile")

    if "ci_only" in marker_names and profile != "ci":
        pytest.skip("ci_only test requires CI profile")

    for marker_name, env_name in REQUIRED_ENV_BY_MARKER.items():
        if marker_name in marker_names and optional_env(env_name) is None:
            pytest.skip(f"{marker_name} requires {env_name}")

    for marker_name in REQUIRED_PKG_BY_MARKER:
        if marker_name in marker_names and not pkgs_available_for_marker(marker_name):
            pytest.skip(f"{marker_name} requires missing Python package(s)")


@pytest.fixture(autouse=True)
def stable_token_counter(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep token counting local and deterministic in tests."""
    from backend.utils import token_estimation

    token_estimation._encoding_cache.clear()
    monkeypatch.setattr(token_estimation, "_tiktoken_available", False)
    yield
    token_estimation._encoding_cache.clear()
