from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.core.exceptions import ResourceNotFound, ValidationError
from backend.models.schemas.user_schema import UserCreate, UserLogin, UserUpdate
from backend.services.user_service import UserService


@pytest.fixture
def service_ctx():
    repo = SimpleNamespace(
        get_by_email=AsyncMock(),
        get_by_username=AsyncMock(),
        create=AsyncMock(),
        get=AsyncMock(),
        update=AsyncMock(),
        get_multi=AsyncMock(),
        remove=AsyncMock(),
    )
    uow = SimpleNamespace(user_repo=repo)
    service = UserService(uow=uow)
    return SimpleNamespace(service=service, repo=repo)


def _build_user_create() -> UserCreate:
    return UserCreate(
        username="new_user",
        email="new_user@example.com",
        password="Password123",
        confirm_password="Password123",
    )


@pytest.mark.asyncio
async def test_user_register_success(service_ctx, monkeypatch):
    user_in = _build_user_create()
    service_ctx.repo.get_by_email.return_value = None
    service_ctx.repo.get_by_username.return_value = None
    created_user = SimpleNamespace(id=uuid.uuid4(), username=user_in.username)
    service_ctx.repo.create.return_value = created_user

    async def fake_hash(password: str) -> str:
        assert password == "Password123"
        return "hashed-password"

    monkeypatch.setattr("backend.services.user_service.get_password_hash", fake_hash)

    result = await service_ctx.service.user_register(user_in)

    assert result == created_user
    create_call = service_ctx.repo.create.await_args.kwargs["obj_in"]
    assert create_call["username"] == "new_user"
    assert create_call["email"] == "new_user@example.com"
    assert create_call["hashed_password"] == "hashed-password"
    assert "password" not in create_call
    assert "confirm_password" not in create_call


@pytest.mark.asyncio
async def test_user_register_rejects_existing_email(service_ctx):
    service_ctx.repo.get_by_email.return_value = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(ValidationError, match="该邮箱已被注册"):
        await service_ctx.service.user_register(_build_user_create())


@pytest.mark.asyncio
async def test_user_register_rejects_existing_username(service_ctx):
    service_ctx.repo.get_by_email.return_value = None
    service_ctx.repo.get_by_username.return_value = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(ValidationError, match="该用户名已被注册"):
        await service_ctx.service.user_register(_build_user_create())


@pytest.mark.asyncio
async def test_user_register_maps_integrity_error_to_validation_error(
    service_ctx, monkeypatch
):
    service_ctx.repo.get_by_email.return_value = None
    service_ctx.repo.get_by_username.return_value = None
    service_ctx.repo.create.side_effect = IntegrityError(
        "insert users", {"username": "new_user"}, Exception("duplicate key")
    )

    async def fake_hash(_: str) -> str:
        return "hashed-password"

    monkeypatch.setattr("backend.services.user_service.get_password_hash", fake_hash)

    with pytest.raises(ValidationError, match="用户名或邮箱已被注册"):
        await service_ctx.service.user_register(_build_user_create())


@pytest.mark.asyncio
async def test_user_update_raises_not_found_when_user_missing(service_ctx):
    service_ctx.repo.get.return_value = None

    with pytest.raises(ResourceNotFound, match="用户不存在"):
        await service_ctx.service.user_update(
            user_id=uuid.uuid4(),
            user_in=UserUpdate(username="new_name"),
        )


@pytest.mark.asyncio
async def test_authenticate_returns_none_when_user_missing(service_ctx):
    service_ctx.repo.get_by_username.return_value = None

    result = await service_ctx.service.authenticate(
        UserLogin(username="new_user", password="Password123")
    )

    assert result is None


@pytest.mark.asyncio
async def test_authenticate_returns_none_when_password_invalid(service_ctx, monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), hashed_password="hashed")
    service_ctx.repo.get_by_username.return_value = user

    async def fake_verify(_, __) -> bool:
        return False

    monkeypatch.setattr("backend.services.user_service.verify_password", fake_verify)

    result = await service_ctx.service.authenticate(
        UserLogin(username="new_user", password="Password123")
    )

    assert result is None


@pytest.mark.asyncio
async def test_authenticate_success(service_ctx, monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), hashed_password="hashed")
    service_ctx.repo.get_by_username.return_value = user

    async def fake_verify(_, __) -> bool:
        return True

    monkeypatch.setattr("backend.services.user_service.verify_password", fake_verify)

    result = await service_ctx.service.authenticate(
        UserLogin(username="new_user", password="Password123")
    )

    assert result == user
