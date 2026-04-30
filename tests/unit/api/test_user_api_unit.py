from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from backend.api.v1.endpoint import user_api
from backend.core.exceptions import AppException
from backend.models.schemas.user_schema import (
    UserCreate,
    UserImportResponse,
    UserSearch,
    UserUpdate,
)


class DummyUoW:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_user(**overrides):
    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "username": "tester",
        "email": "tester@example.com",
        "is_active": True,
        "is_superuser": False,
        "max_tokens": 100000,
        "used_tokens": 0,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.fixture
def user_service():
    service = SimpleNamespace(
        uow=DummyUoW(),
        get_by_username=AsyncMock(),
        get_by_email=AsyncMock(),
        user_update=AsyncMock(),
        user_register_with_personal_workspace=AsyncMock(),
    )
    return service


@pytest.fixture
def import_service():
    service = SimpleNamespace(
        uow=DummyUoW(),
        import_from_upload=AsyncMock(),
    )
    return service


@pytest.mark.asyncio
async def test_read_users_me_returns_user_response():
    current_user = make_user(username="me_user", email="me@example.com")

    result = await user_api.read_users_me(current_user=current_user)

    assert result.id == current_user.id
    assert result.username == "me_user"
    assert result.email == "me@example.com"


@pytest.mark.asyncio
async def test_read_user_uses_username_branch(user_service):
    target = make_user(username="alice", email="alice@example.com")
    user_service.get_by_username.return_value = target

    result = await user_api.read_user(
        search_params=UserSearch(username="alice"),
        _=make_user(is_superuser=True),
        user_service=user_service,
    )

    assert result.username == "alice"
    user_service.get_by_username.assert_awaited_once_with("alice")
    user_service.get_by_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_user_uses_email_branch(user_service):
    target = make_user(username="alice", email="alice@example.com")
    user_service.get_by_email.return_value = target

    result = await user_api.read_user(
        search_params=UserSearch(email="alice@example.com"),
        _=make_user(is_superuser=True),
        user_service=user_service,
    )

    assert result.email == "alice@example.com"
    user_service.get_by_email.assert_awaited_once_with("alice@example.com")
    user_service.get_by_username.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_user_returns_404_when_not_found(user_service):
    user_service.get_by_username.return_value = None

    with pytest.raises(AppException) as exc_info:
        await user_api.read_user(
            search_params=UserSearch(username="missing"),
            _=make_user(is_superuser=True),
            user_service=user_service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "User not found"


@pytest.mark.asyncio
async def test_update_user_success(user_service):
    user_id = uuid.uuid4()
    user_in = UserUpdate(username="new_name")
    updated = make_user(id=user_id, username="new_name")
    user_service.user_update.return_value = updated

    result = await user_api.update_user(
        user_id=user_id,
        user_in=user_in,
        _=make_user(is_superuser=True),
        user_service=user_service,
    )

    assert result.id == user_id
    assert result.username == "new_name"
    user_service.user_update.assert_awaited_once_with(user_id=user_id, user_in=user_in)


@pytest.mark.asyncio
async def test_update_user_returns_404_when_not_found(user_service):
    user_service.user_update.return_value = None

    with pytest.raises(AppException) as exc_info:
        await user_api.update_user(
            user_id=uuid.uuid4(),
            user_in=UserUpdate(username="new_name"),
            _=make_user(is_superuser=True),
            user_service=user_service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "User not found"


@pytest.mark.asyncio
async def test_create_user_success(user_service):
    user_in = UserCreate(
        username="new_user",
        email="new_user@example.com",
        password="Password123",
        confirm_password="Password123",
    )
    created = make_user(username="new_user", email="new_user@example.com")
    user_service.user_register_with_personal_workspace.return_value = created

    result = await user_api.create_user(
        user_in=user_in,
        _=make_user(is_superuser=True),
        user_service=user_service,
    )

    assert result.username == "new_user"
    user_service.user_register_with_personal_workspace.assert_awaited_once_with(user_in)


@pytest.mark.asyncio
async def test_create_user_returns_400_when_service_returns_none(user_service):
    user_service.user_register_with_personal_workspace.return_value = None

    with pytest.raises(AppException) as exc_info:
        await user_api.create_user(
            user_in=UserCreate(
                username="new_user",
                email="new_user@example.com",
                password="Password123",
                confirm_password="Password123",
            ),
            _=make_user(is_superuser=True),
            user_service=user_service,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.message == "User creation failed"


@pytest.mark.asyncio
async def test_csv_bulk_insert_users_success(import_service):
    upload_file = MagicMock(spec=UploadFile)
    expected = UserImportResponse(
        filename="users.csv",
        total_rows=2,
        imported_rows=2,
        message="成功导入 2 条用户数据",
    )
    import_service.import_from_upload.return_value = expected

    result = await user_api.csv_balk_insert_users(
        file=upload_file,
        _=make_user(is_superuser=True),
        import_service=import_service,
    )

    assert result == expected
    import_service.import_from_upload.assert_awaited_once_with(upload_file)
