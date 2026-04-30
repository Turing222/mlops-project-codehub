from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.v1.endpoint import user_api
from backend.core.exceptions import app_forbidden, setup_exception_handlers
from backend.models.schemas.user_schema import UserImportResponse


class DummyUoW:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class StubUserService:
    def __init__(self):
        self.uow = DummyUoW()
        self.get_by_username = AsyncMock()
        self.get_by_email = AsyncMock()
        self.user_update = AsyncMock()
        self.user_register_with_personal_workspace = AsyncMock()


class StubUserImportService:
    def __init__(self):
        self.uow = DummyUoW()
        self.import_from_upload = AsyncMock()


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
def api_context():
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(user_api.router, prefix="/api/v1/users")

    current_user = make_user(username="me_user")
    super_user = make_user(username="admin_user", is_superuser=True)
    user_service = StubUserService()
    import_service = StubUserImportService()

    app.dependency_overrides[user_api.get_current_active_user] = lambda: current_user
    app.dependency_overrides[user_api.get_current_superuser] = lambda: super_user
    app.dependency_overrides[user_api.get_user_service] = lambda: user_service
    app.dependency_overrides[user_api.get_user_import_service] = lambda: import_service
    app.dependency_overrides[user_api.get_permission_service] = lambda: SimpleNamespace()
    app.dependency_overrides[user_api.get_audit_service] = lambda: SimpleNamespace()

    ctx = SimpleNamespace(
        app=app,
        current_user=current_user,
        super_user=super_user,
        user_service=user_service,
        import_service=import_service,
    )
    yield ctx
    app.dependency_overrides.clear()


@pytest.fixture
async def client(api_context):
    transport = ASGITransport(app=api_context.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_read_users_me_success(client, api_context):
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(api_context.current_user.id)
    assert body["username"] == api_context.current_user.username
    assert body["email"] == api_context.current_user.email


@pytest.mark.asyncio
async def test_read_user_by_username_success(client, api_context):
    target = make_user(username="target_user", email="target@example.com")
    api_context.user_service.get_by_username.return_value = target

    response = await client.get("/api/v1/users", params={"username": "target_user"})

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "target_user"
    assert body["email"] == "target@example.com"
    api_context.user_service.get_by_username.assert_awaited_once_with("target_user")
    api_context.user_service.get_by_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_user_by_email_success(client, api_context):
    target = make_user(username="target_user", email="target@example.com")
    api_context.user_service.get_by_email.return_value = target

    response = await client.get("/api/v1/users", params={"email": "target@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "target_user"
    assert body["email"] == "target@example.com"
    api_context.user_service.get_by_email.assert_awaited_once_with("target@example.com")
    api_context.user_service.get_by_username.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_user_not_found_returns_404(client, api_context):
    api_context.user_service.get_by_username.return_value = None

    response = await client.get("/api/v1/users", params={"username": "not_exists"})

    assert response.status_code == 404
    assert response.json()["message"] == "User not found"


@pytest.mark.asyncio
async def test_update_user_success(client, api_context):
    user_id = uuid.uuid4()
    updated = make_user(id=user_id, username="new_name", email="new@example.com")
    api_context.user_service.user_update.return_value = updated

    response = await client.patch(
        f"/api/v1/users/{user_id}",
        json={"username": "new_name"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["username"] == "new_name"

    call_kwargs = api_context.user_service.user_update.await_args.kwargs
    assert call_kwargs["user_id"] == user_id
    assert call_kwargs["user_in"].username == "new_name"


@pytest.mark.asyncio
async def test_update_user_not_found_returns_404(client, api_context):
    api_context.user_service.user_update.return_value = None
    user_id = uuid.uuid4()

    response = await client.patch(
        f"/api/v1/users/{user_id}",
        json={"username": "new_name"},
    )

    assert response.status_code == 404
    assert response.json()["message"] == "User not found"


@pytest.mark.asyncio
async def test_create_user_success(client, api_context):
    created = make_user(username="fresh_user", email="fresh@example.com")
    api_context.user_service.user_register_with_personal_workspace.return_value = created

    payload = {
        "username": "fresh_user",
        "email": "fresh@example.com",
        "password": "Password123",
        "confirm_password": "Password123",
        "max_tokens": 200000,
    }
    response = await client.post("/api/v1/users", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "fresh_user"
    assert body["email"] == "fresh@example.com"
    api_context.user_service.user_register_with_personal_workspace.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_user_returns_400_when_service_returns_none(client, api_context):
    api_context.user_service.user_register_with_personal_workspace.return_value = None
    payload = {
        "username": "fresh_user",
        "email": "fresh@example.com",
        "password": "Password123",
        "confirm_password": "Password123",
    }

    response = await client.post("/api/v1/users", json=payload)

    assert response.status_code == 400
    assert response.json()["message"] == "User creation failed"


@pytest.mark.asyncio
async def test_create_user_invalid_payload_returns_422(client):
    payload = {
        "username": "fresh_user",
        "email": "fresh@example.com",
        "password": "Password123",
        "confirm_password": "Mismatch123",
    }

    response = await client.post("/api/v1/users", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_csv_upload_success(client, api_context):
    api_context.import_service.import_from_upload.return_value = UserImportResponse(
        filename="users.csv",
        total_rows=2,
        imported_rows=2,
        message="成功导入 2 条用户数据",
    )

    response = await client.post(
        "/api/v1/users/csv_upload",
        files={
            "file": ("users.csv", b"username,email\nu1,u1@example.com\n", "text/csv")
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "users.csv"
    assert body["imported_rows"] == 2
    api_context.import_service.import_from_upload.assert_awaited_once()


@pytest.mark.asyncio
async def test_csv_upload_missing_file_returns_422(client):
    response = await client.post("/api/v1/users/csv_upload", files={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_superuser_required_on_admin_endpoint(client, api_context):
    def deny_superuser():
        raise app_forbidden("权限不足")

    api_context.app.dependency_overrides[user_api.get_current_superuser] = (
        deny_superuser
    )
    response = await client.get("/api/v1/users", params={"username": "target_user"})

    assert response.status_code == 403
    assert response.json()["message"] == "权限不足"
