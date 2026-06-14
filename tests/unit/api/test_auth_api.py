"""Auth API unit tests.

职责：验证认证 endpoint 的轻量响应组装；边界：直接调用 endpoint 函数，不启动 ASGI。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute

from backend.api.v1.endpoint import auth_api
from backend.models.schemas.user_schema import SMSSendRequest

pytestmark = pytest.mark.asyncio


async def test_sms_send_never_returns_mock_code() -> None:
    sms_service = SimpleNamespace(send_code=AsyncMock(return_value="123456"))

    response = await auth_api.sms_send(
        body=SMSSendRequest(phone="13800138000"),
        sms_service=sms_service,
    )

    assert response.message == "验证码已发送"
    assert not hasattr(response, "code")
    sms_service.send_code.assert_awaited_once_with("13800138000")


def _route_dependencies(path: str, method: str) -> list[object]:
    for route in auth_api.router.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method in route.methods
        ):
            return [dependency.call for dependency in route.dependant.dependencies]
    raise AssertionError(f"Route not found: {method} {path}")


async def test_sms_login_has_dedicated_rate_limiter() -> None:
    dependencies = _route_dependencies("/sms/login", "POST")

    assert auth_api.sms_login_limiter in dependencies


async def test_google_callback_has_dedicated_rate_limiter() -> None:
    dependencies = _route_dependencies("/google/callback", "POST")

    assert auth_api.google_callback_limiter in dependencies
