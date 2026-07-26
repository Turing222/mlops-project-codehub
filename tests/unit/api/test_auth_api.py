"""Auth API unit tests.

职责：验证认证 endpoint 的轻量响应组装；边界：直接调用 endpoint 函数，不启动 ASGI。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute

from backend.api.v1.endpoint import auth_api
from backend.core.exceptions import AppException
from backend.models.schemas.user_schema import SMSSendRequest, UserCreate


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


def _registration_flags(*, public_registration: bool) -> SimpleNamespace:
    return SimpleNamespace(
        get_system_features=AsyncMock(
            return_value={"enable-public-registration": public_registration}
        )
    )


async def test_register_rejected_when_public_registration_disabled() -> None:
    user_service = SimpleNamespace(user_register_with_personal_workspace=AsyncMock())

    with pytest.raises(AppException) as exc_info:
        await auth_api.register(
            user_in=UserCreate(username="closed_beta_probe", password="Str0ngPass!23"),
            user_service=user_service,
            feature_flag_service=_registration_flags(public_registration=False),
        )

    assert exc_info.value.code == "REGISTRATION_CLOSED"
    user_service.user_register_with_personal_workspace.assert_not_awaited()


async def test_register_rejects_missing_password() -> None:
    """公开注册不允许创建无密码账号，即使注册开关是开启状态。"""
    user_service = SimpleNamespace(user_register_with_personal_workspace=AsyncMock())

    with pytest.raises(AppException) as exc_info:
        await auth_api.register(
            user_in=UserCreate(username="passwordless_probe"),
            user_service=user_service,
            feature_flag_service=_registration_flags(public_registration=True),
        )

    assert exc_info.value.code == "REGISTRATION_PASSWORD_REQUIRED"
    user_service.user_register_with_personal_workspace.assert_not_awaited()
