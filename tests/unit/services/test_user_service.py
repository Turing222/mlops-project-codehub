"""User service unit tests.

职责：验证 UserService 的注册、认证和工作空间创建行为；边界：使用 SimpleNamespace mock 和 monkeypatch，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.core.exceptions import AppException
from backend.models.orm.access import WorkspaceRole
from backend.models.schemas.user_schema import UserCreate, UserLogin, UserUpdate
from backend.services.user_service import UserService


@pytest.fixture
def user_service_ctx() -> SimpleNamespace:
    repo = SimpleNamespace(
        get_by_email=AsyncMock(),
        get_by_username=AsyncMock(),
        get_by_phone=AsyncMock(),
        get_by_google_sub=AsyncMock(),
        create=AsyncMock(),
        get=AsyncMock(),
        update=AsyncMock(),
        get_multi=AsyncMock(),
        remove=AsyncMock(),
    )
    access_repo = SimpleNamespace(
        create_workspace=AsyncMock(),
        add_workspace_role=AsyncMock(),
    )

    @asynccontextmanager
    async def _noop_savepoint():
        yield uow

    uow = cast(
        AbstractUnitOfWork,
        SimpleNamespace(
            user_repo=repo, access_repo=access_repo, savepoint=_noop_savepoint
        ),
    )
    service = UserService(uow=uow)
    return SimpleNamespace(service=service, repo=repo, access_repo=access_repo, uow=uow)


def _build_user_create() -> UserCreate:
    return UserCreate(
        username="new_user",
        email="new_user@example.com",
        password="Password123",
        confirm_password="Password123",
    )


@pytest.mark.asyncio
async def test_user_register_returns_created_user(
    user_service_ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_in = _build_user_create()
    user_service_ctx.repo.get_by_email.return_value = None
    user_service_ctx.repo.get_by_username.return_value = None
    created_user = SimpleNamespace(id=uuid.uuid4(), username=user_in.username)
    user_service_ctx.repo.create.return_value = created_user

    async def fake_hash(password: str) -> str:
        assert password == "Password123"
        return "hashed-password"

    monkeypatch.setattr("backend.services.user_service.get_password_hash", fake_hash)

    result = await user_service_ctx.service.user_register(user_in)

    assert result == created_user
    create_call = user_service_ctx.repo.create.await_args.kwargs["obj_in"]
    assert create_call["username"] == "new_user"
    assert create_call["email"] == "new_user@example.com"
    assert create_call["hashed_password"] == "hashed-password"
    assert "password" not in create_call
    assert "confirm_password" not in create_call


@pytest.mark.asyncio
async def test_user_register_with_personal_workspace_creates_owner_workspace_role(
    user_service_ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_in = _build_user_create()
    user_id = uuid.uuid4()
    created_user = SimpleNamespace(id=user_id, username=user_in.username)
    workspace = SimpleNamespace(id=uuid.uuid4())
    user_service_ctx.repo.get_by_email.return_value = None
    user_service_ctx.repo.get_by_username.return_value = None
    user_service_ctx.repo.create.return_value = created_user
    user_service_ctx.access_repo.create_workspace.return_value = workspace

    async def fake_hash(_: str) -> str:
        return "hashed-password"

    monkeypatch.setattr("backend.services.user_service.get_password_hash", fake_hash)

    result = await user_service_ctx.service.user_register_with_personal_workspace(
        user_in
    )

    assert result is created_user
    user_service_ctx.access_repo.create_workspace.assert_awaited_once_with(
        name="new_user's Workspace",
        slug=f"new_user-{user_id.hex[:8]}",
        owner_id=user_id,
    )
    user_service_ctx.access_repo.add_workspace_role.assert_awaited_once_with(
        user_id=user_id,
        workspace_id=workspace.id,
        role=WorkspaceRole.OWNER,
    )


def test_user_create_forbids_role_and_workspace_fields_raises_validation_error() -> (
    None
):
    with pytest.raises(ValueError):
        UserCreate.model_validate(
            {
                "username": "new_user",
                "email": "new_user@example.com",
                "password": "Password123",
                "confirm_password": "Password123",
                "role": "owner",
            }
        )


@pytest.mark.asyncio
async def test_user_register_rejects_existing_email(
    user_service_ctx: SimpleNamespace,
) -> None:
    user_service_ctx.repo.get_by_email.return_value = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(AppException, match="该邮箱已被注册"):
        await user_service_ctx.service.user_register(_build_user_create())


@pytest.mark.asyncio
async def test_user_register_rejects_existing_username(
    user_service_ctx: SimpleNamespace,
) -> None:
    user_service_ctx.repo.get_by_email.return_value = None
    user_service_ctx.repo.get_by_username.return_value = SimpleNamespace(
        id=uuid.uuid4()
    )

    with pytest.raises(AppException, match="该用户名已被注册"):
        await user_service_ctx.service.user_register(_build_user_create())


@pytest.mark.asyncio
async def test_user_register_maps_integrity_error_to_validation_error(
    user_service_ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_service_ctx.repo.get_by_email.return_value = None
    user_service_ctx.repo.get_by_username.return_value = None
    user_service_ctx.repo.create.side_effect = IntegrityError(
        "insert users", {"username": "new_user"}, Exception("duplicate key")
    )

    async def fake_hash(_: str) -> str:
        return "hashed-password"

    monkeypatch.setattr("backend.services.user_service.get_password_hash", fake_hash)

    with pytest.raises(AppException, match="用户名或邮箱已被注册"):
        await user_service_ctx.service.user_register(_build_user_create())


@pytest.mark.asyncio
async def test_user_update_raises_not_found_when_user_missing(
    user_service_ctx: SimpleNamespace,
) -> None:
    user_service_ctx.repo.get.return_value = None

    with pytest.raises(AppException, match="用户不存在"):
        await user_service_ctx.service.user_update(
            user_id=uuid.uuid4(),
            user_in=UserUpdate(username="new_name"),
        )


@pytest.mark.asyncio
async def test_user_update_rejects_existing_username(
    user_service_ctx: SimpleNamespace,
) -> None:
    user_id = uuid.uuid4()
    user_service_ctx.repo.get.return_value = SimpleNamespace(
        id=user_id,
        username="old_name",
        email="old@example.com",
        phone=None,
    )
    user_service_ctx.repo.get_by_username.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        username="new_name",
    )

    with pytest.raises(AppException, match="该用户名已被注册"):
        await user_service_ctx.service.user_update(
            user_id=user_id,
            user_in=UserUpdate(username="new_name"),
        )


@pytest.mark.asyncio
async def test_user_update_rejects_existing_email(
    user_service_ctx: SimpleNamespace,
) -> None:
    user_id = uuid.uuid4()
    user_service_ctx.repo.get.return_value = SimpleNamespace(
        id=user_id,
        username="old_name",
        email="old@example.com",
        phone=None,
    )
    user_service_ctx.repo.get_by_email.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        email="new@example.com",
    )

    with pytest.raises(AppException, match="该邮箱已被注册"):
        await user_service_ctx.service.user_update(
            user_id=user_id,
            user_in=UserUpdate(email="new@example.com"),
        )


@pytest.mark.asyncio
async def test_user_update_rejects_existing_phone(
    user_service_ctx: SimpleNamespace,
) -> None:
    user_id = uuid.uuid4()
    user_service_ctx.repo.get.return_value = SimpleNamespace(
        id=user_id,
        username="old_name",
        email="old@example.com",
        phone="13800000000",
    )
    user_service_ctx.repo.get_by_phone.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        phone="13900000000",
    )

    with pytest.raises(AppException, match="该手机号已被注册"):
        await user_service_ctx.service.user_update(
            user_id=user_id,
            user_in=UserUpdate(phone="13900000000"),
        )


@pytest.mark.asyncio
async def test_user_update_maps_integrity_error_to_validation_error(
    user_service_ctx: SimpleNamespace,
) -> None:
    user_id = uuid.uuid4()
    user_service_ctx.repo.get.return_value = SimpleNamespace(
        id=user_id,
        username="old_name",
        email="old@example.com",
        phone=None,
    )
    user_service_ctx.repo.get_by_username.return_value = None
    user_service_ctx.repo.update.side_effect = IntegrityError(
        "update users", {"username": "new_name"}, Exception("duplicate key")
    )

    with pytest.raises(AppException, match="用户名、邮箱或手机号已被注册"):
        await user_service_ctx.service.user_update(
            user_id=user_id,
            user_in=UserUpdate(username="new_name"),
        )


@pytest.mark.asyncio
async def test_authenticate_returns_none_when_user_missing(
    user_service_ctx: SimpleNamespace,
) -> None:
    user_service_ctx.repo.get_by_username.return_value = None

    result = await user_service_ctx.service.authenticate(
        UserLogin(username="new_user", password="Password123")
    )

    assert result is None


@pytest.mark.asyncio
async def test_authenticate_returns_none_when_password_invalid(
    user_service_ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = SimpleNamespace(id=uuid.uuid4(), hashed_password="hashed")
    user_service_ctx.repo.get_by_username.return_value = user

    async def fake_verify(_: str, __: str) -> bool:
        return False

    monkeypatch.setattr("backend.services.user_service.verify_password", fake_verify)

    result = await user_service_ctx.service.authenticate(
        UserLogin(username="new_user", password="Password123")
    )

    assert result is None


@pytest.mark.asyncio
async def test_authenticate_returns_user_on_valid_credentials(
    user_service_ctx: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = SimpleNamespace(id=uuid.uuid4(), hashed_password="hashed")
    user_service_ctx.repo.get_by_username.return_value = user

    async def fake_verify(_: str, __: str) -> bool:
        return True

    monkeypatch.setattr("backend.services.user_service.verify_password", fake_verify)

    result = await user_service_ctx.service.authenticate(
        UserLogin(username="new_user", password="Password123")
    )

    assert result == user


@pytest.mark.asyncio
async def test_find_or_create_by_phone_recovers_from_integrity_error(
    user_service_ctx: SimpleNamespace,
) -> None:
    """Concurrent phone registration: IntegrityError → savepoint recovery → re-query."""
    existing_user = SimpleNamespace(id=uuid.uuid4(), phone="13800000000")
    user_service_ctx.repo.get_by_phone.return_value = None
    user_service_ctx.repo.get_by_username.return_value = None
    user_service_ctx.repo.create.side_effect = IntegrityError(
        "insert users", {"phone": "13800000000"}, Exception("duplicate key")
    )
    # Second get_by_phone call returns the user created by the concurrent request
    user_service_ctx.repo.get_by_phone.side_effect = [None, existing_user]

    result = await user_service_ctx.service.find_or_create_by_phone("13800000000")

    assert result is existing_user


@pytest.mark.asyncio
async def test_find_or_create_by_google_recovers_from_integrity_error(
    user_service_ctx: SimpleNamespace,
) -> None:
    """Concurrent Google registration: IntegrityError → savepoint recovery → re-query."""
    google_sub = "google_123"
    existing_user = SimpleNamespace(id=uuid.uuid4(), google_sub=google_sub)
    user_service_ctx.repo.get_by_google_sub.return_value = None
    user_service_ctx.repo.get_by_email.return_value = None
    user_service_ctx.repo.get_by_username.return_value = None
    user_service_ctx.repo.create.side_effect = IntegrityError(
        "insert users", {"google_sub": google_sub}, Exception("duplicate key")
    )
    user_service_ctx.repo.get_by_google_sub.side_effect = [None, existing_user]

    result = await user_service_ctx.service.find_or_create_by_google(
        google_sub=google_sub, email=None, name=None
    )

    assert result is existing_user


@pytest.mark.asyncio
async def test_find_or_create_by_google_links_email_user_after_integrity_error(
    user_service_ctx: SimpleNamespace,
) -> None:
    """Concurrent Google registration can recover via email and still bind sub."""
    google_sub = "google_456"
    email = "linked@example.com"
    existing_user_id = uuid.uuid4()
    existing_user = SimpleNamespace(
        id=existing_user_id,
        email=email,
        auth_provider=None,
    )
    user_service_ctx.repo.get_by_google_sub.return_value = None
    user_service_ctx.repo.get_by_email.side_effect = [None, existing_user]
    user_service_ctx.repo.get_by_username.return_value = None
    user_service_ctx.repo.create.side_effect = IntegrityError(
        "insert users", {"email": email}, Exception("duplicate key")
    )
    user_service_ctx.repo.get.return_value = existing_user

    result = await user_service_ctx.service.find_or_create_by_google(
        google_sub=google_sub,
        email=email,
        name=None,
    )

    assert result is existing_user
    user_service_ctx.repo.update.assert_awaited_once_with(
        db_obj=existing_user,
        obj_in={"google_sub": google_sub, "auth_provider": "google"},
    )


@pytest.mark.asyncio
async def test_find_or_create_by_phone_raises_when_registration_closed(
    user_service_ctx: SimpleNamespace,
) -> None:
    """When allow_new_registration=False and no existing user, raise REGISTRATION_CLOSED."""
    user_service_ctx.repo.get_by_phone.return_value = None

    with pytest.raises(AppException, match="封闭内测") as exc_info:
        await user_service_ctx.service.find_or_create_by_phone(
            "13800000000", allow_new_registration=False
        )
    assert exc_info.value.code == "REGISTRATION_CLOSED"
    user_service_ctx.repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_or_create_by_phone_returns_existing_when_registration_closed(
    user_service_ctx: SimpleNamespace,
) -> None:
    """When allow_new_registration=False but user exists, return normally."""
    existing = SimpleNamespace(id=uuid.uuid4(), phone="13800000000")
    user_service_ctx.repo.get_by_phone.return_value = existing

    result = await user_service_ctx.service.find_or_create_by_phone(
        "13800000000", allow_new_registration=False
    )
    assert result is existing


@pytest.mark.asyncio
async def test_find_or_create_by_google_raises_when_registration_closed(
    user_service_ctx: SimpleNamespace,
) -> None:
    """When allow_new_registration=False and no existing user, raise REGISTRATION_CLOSED."""
    user_service_ctx.repo.get_by_google_sub.return_value = None
    user_service_ctx.repo.get_by_email.return_value = None

    with pytest.raises(AppException, match="封闭内测") as exc_info:
        await user_service_ctx.service.find_or_create_by_google(
            google_sub="google_new",
            email="new@example.com",
            name="New User",
            allow_new_registration=False,
        )
    assert exc_info.value.code == "REGISTRATION_CLOSED"
    user_service_ctx.repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_or_create_by_google_returns_existing_when_registration_closed(
    user_service_ctx: SimpleNamespace,
) -> None:
    """When allow_new_registration=False but user exists by google_sub, return normally."""
    existing = SimpleNamespace(id=uuid.uuid4(), google_sub="google_existing")
    user_service_ctx.repo.get_by_google_sub.return_value = existing

    result = await user_service_ctx.service.find_or_create_by_google(
        google_sub="google_existing",
        email="existing@example.com",
        name="Existing User",
        allow_new_registration=False,
    )
    assert result is existing
