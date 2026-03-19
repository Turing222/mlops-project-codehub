from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.deps import auth


class DummyUoW:
    def __init__(self):
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_count += 1
        return False


def make_user(**overrides):
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
def auth_ctx():
    uow = DummyUoW()
    fake_service = SimpleNamespace(get_by_id=AsyncMock())
    return SimpleNamespace(uow=uow, fake_service=fake_service)


def _patch_auth(monkeypatch, auth_ctx, payload: dict):
    monkeypatch.setattr("backend.api.deps.auth.jwt.decode", lambda *args, **kwargs: payload)
    monkeypatch.setattr(
        "backend.api.deps.auth.UserService",
        lambda uow: auth_ctx.fake_service,
    )


def test_get_login_data_maps_form_to_schema():
    form_data = SimpleNamespace(username="alice_01", password="Password123")

    result = auth.get_login_data(form_data=form_data)

    assert result.username == "alice_01"
    assert result.password == "Password123"


def test_get_login_data_returns_422_for_invalid_form():
    form_data = SimpleNamespace(username="ab", password="short")

    with pytest.raises(HTTPException) as exc_info:
        auth.get_login_data(form_data=form_data)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail


@pytest.mark.asyncio
async def test_get_current_user_returns_loaded_user(monkeypatch, auth_ctx):
    user = make_user()
    _patch_auth(monkeypatch, auth_ctx, {"sub": str(user.id)})
    auth_ctx.fake_service.get_by_id.return_value = user

    result = await auth.get_current_user(uow=auth_ctx.uow, token="good-token")

    assert result == user
    auth_ctx.fake_service.get_by_id.assert_awaited_once_with(str(user.id))
    assert auth_ctx.uow.enter_count == 1
    assert auth_ctx.uow.exit_count == 1


@pytest.mark.asyncio
async def test_get_current_user_returns_403_for_invalid_token(monkeypatch, auth_ctx):
    def raise_invalid_token(*args, **kwargs):
        raise auth.InvalidTokenError("bad token")

    monkeypatch.setattr("backend.api.deps.auth.jwt.decode", raise_invalid_token)

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user(uow=auth_ctx.uow, token="bad-token")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Token 无效或已过期"


@pytest.mark.asyncio
async def test_get_current_user_returns_403_when_subject_missing(monkeypatch, auth_ctx):
    _patch_auth(monkeypatch, auth_ctx, {})

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user(uow=auth_ctx.uow, token="missing-sub")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Token 缺少身份标识"


@pytest.mark.asyncio
async def test_get_current_user_returns_404_when_user_missing(monkeypatch, auth_ctx):
    _patch_auth(monkeypatch, auth_ctx, {"sub": "user-404"})
    auth_ctx.fake_service.get_by_id.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await auth.get_current_user(uow=auth_ctx.uow, token="good-token")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "用户不存在"


def test_get_current_active_user_returns_user_when_active():
    user = make_user(is_active=True)

    assert auth.get_current_active_user(current_user=user) == user


def test_get_current_active_user_returns_400_when_inactive():
    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_active_user(current_user=make_user(is_active=False))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "用户账户未激活"


def test_get_current_superuser_returns_user_when_superuser():
    user = make_user(is_superuser=True)

    assert auth.get_current_superuser(current_user=user) == user


def test_get_current_superuser_returns_403_when_not_superuser():
    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_superuser(current_user=make_user(is_superuser=False))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "权限不足"
