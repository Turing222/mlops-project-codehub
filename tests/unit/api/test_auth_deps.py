"""Authentication dependency unit tests.

职责：验证认证依赖的表单映射、JWT 解析和用户状态检查；边界：使用 fake UoW/service，直接调用依赖函数；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.api.deps import auth
from backend.core.exceptions import AppException


class DummyUoW:
    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0

    def read_context(self) -> DummyUoW:
        return self

    async def __aenter__(self) -> DummyUoW:
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.exit_count += 1
        return False


def make_user(**overrides: object) -> SimpleNamespace:
    data = {
        "id": uuid.uuid4(),
        "username": "tester",
        "email": "tester@example.com",
        "is_active": True,
        "is_superuser": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.fixture
def auth_ctx() -> SimpleNamespace:
    uow = DummyUoW()
    fake_service = SimpleNamespace(get_by_id=AsyncMock())
    return SimpleNamespace(uow=uow, fake_service=fake_service)


def _patch_jwt_decode(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        "backend.api.deps.auth.jwt.decode", lambda *args, **kwargs: payload
    )


def test_get_login_data_maps_form_to_schema() -> None:
    form_data = SimpleNamespace(username="alice_01", password="Password123")

    result = auth.get_login_data(form_data=form_data)

    assert result.username == "alice_01"
    assert result.password == "Password123"


def test_get_login_data_returns_422_for_invalid_form() -> None:
    form_data = SimpleNamespace(username="ab", password="short")

    with pytest.raises(AppException) as exc_info:
        auth.get_login_data(form_data=form_data)

    assert exc_info.value.status_code == 422
    assert exc_info.value.details


async def test_get_current_user_returns_loaded_user(
    monkeypatch: pytest.MonkeyPatch,
    auth_ctx: SimpleNamespace,
) -> None:
    user = make_user()
    _patch_jwt_decode(monkeypatch, {"sub": str(user.id)})
    auth_ctx.fake_service.get_by_id.return_value = user

    result = await auth.get_current_user(
        uow=auth_ctx.uow,
        token="good-token",
        user_service=auth_ctx.fake_service,
    )

    assert result == user
    auth_ctx.fake_service.get_by_id.assert_awaited_once_with(str(user.id))
    assert auth_ctx.uow.enter_count == 1
    assert auth_ctx.uow.exit_count == 1


async def test_get_current_user_returns_403_for_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
    auth_ctx: SimpleNamespace,
) -> None:
    def raise_invalid_token(*args: object, **kwargs: object) -> None:
        raise auth.InvalidTokenError("bad token")

    monkeypatch.setattr("backend.api.deps.auth.jwt.decode", raise_invalid_token)

    with pytest.raises(AppException) as exc_info:
        await auth.get_current_user(
            uow=auth_ctx.uow,
            token="bad-token",
            user_service=auth_ctx.fake_service,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Token 无效或已过期"


async def test_get_current_user_returns_403_when_subject_missing(
    monkeypatch: pytest.MonkeyPatch,
    auth_ctx: SimpleNamespace,
) -> None:
    _patch_jwt_decode(monkeypatch, {})

    with pytest.raises(AppException) as exc_info:
        await auth.get_current_user(
            uow=auth_ctx.uow,
            token="missing-sub",
            user_service=auth_ctx.fake_service,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "Token 缺少身份标识"


async def test_get_current_user_returns_404_when_user_missing(
    monkeypatch: pytest.MonkeyPatch,
    auth_ctx: SimpleNamespace,
) -> None:
    _patch_jwt_decode(monkeypatch, {"sub": "user-404"})
    auth_ctx.fake_service.get_by_id.return_value = None

    with pytest.raises(AppException) as exc_info:
        await auth.get_current_user(
            uow=auth_ctx.uow,
            token="good-token",
            user_service=auth_ctx.fake_service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "用户不存在"


def test_get_current_active_user_returns_user_when_active() -> None:
    user = make_user(is_active=True)

    assert auth.get_current_active_user(current_user=user) == user


def test_get_current_active_user_returns_400_when_inactive() -> None:
    with pytest.raises(AppException) as exc_info:
        auth.get_current_active_user(current_user=make_user(is_active=False))

    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "用户账户未激活"


def test_get_current_superuser_returns_user_when_superuser() -> None:
    user = make_user(is_superuser=True)

    assert auth.get_current_superuser(current_user=user) == user


def test_get_current_superuser_returns_403_when_not_superuser() -> None:
    with pytest.raises(AppException) as exc_info:
        auth.get_current_superuser(current_user=make_user(is_superuser=False))

    assert exc_info.value.status_code == 403
    assert exc_info.value.message == "权限不足"
