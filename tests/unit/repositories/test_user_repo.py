"""User repository unit tests.

职责：验证 UserRepository 的查询、创建、批量 upsert 和 token 递增行为；边界：使用 AsyncMock session，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.repositories.user_repo import UserCreateData, UserRepository

pytestmark = pytest.mark.asyncio


@pytest.fixture
def repo_ctx() -> tuple[UserRepository, AsyncMock]:
    session = AsyncMock()
    repo = UserRepository(session=session)
    return repo, session


async def test_get_by_email_returns_first_match(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    expected = MagicMock()
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.first.return_value = expected
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.get_by_email("alice@example.com")

    assert result is expected
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "users.email" in sql


async def test_get_by_username_returns_first_match(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    expected = MagicMock()
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.first.return_value = expected
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.get_by_username("alice")

    assert result is expected
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "users.username" in sql


async def test_get_existing_usernames_returns_empty_set_on_empty_input(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx

    result = await repo.get_existing_usernames([])

    assert result == set()
    session.execute.assert_not_awaited()


async def test_get_existing_usernames_returns_deduplicated_set(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = ["alice", "bob", "alice"]
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.get_existing_usernames(["alice", "bob", "charlie"])

    assert result == {"alice", "bob"}
    session.execute.assert_awaited_once()


async def test_get_multi_returns_empty_sequence(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = []
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.get_multi()

    assert result == []


async def test_create_passes_persistence_data_only_returns_created(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, _ = repo_ctx
    expected = MagicMock()
    repo.crud.create = AsyncMock(return_value=expected)
    obj_in = UserCreateData(
        username="alice",
        email="alice@example.com",
        hashed_password="hashed-password",
        max_tokens=100000,
    )

    result = await repo.create(obj_in=obj_in)

    assert result is expected
    create_data = repo.crud.create.await_args.kwargs["obj_in"]
    assert create_data == {
        "username": "alice",
        "email": "alice@example.com",
        "hashed_password": "hashed-password",
        "max_tokens": 100000,
        "phone": None,
        "auth_provider": None,
        "google_sub": None,
    }
    assert "password" not in create_data
    assert "confirm_password" not in create_data


async def test_bulk_upsert_raises_value_error_on_missing_keys(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, _ = repo_ctx

    with pytest.raises(ValueError, match="missing required keys"):
        await repo.bulk_upsert(
            [
                {
                    "username": "alice",
                    "email": "alice@example.com",
                    # hashed_password intentionally missing
                }
            ]
        )


async def test_bulk_upsert_executes_upsert_statement(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx

    await repo.bulk_upsert(
        [
            {
                "username": "alice",
                "email": "alice@example.com",
                "hashed_password": "hash-a",
            },
            {
                "username": "bob",
                "email": "bob@example.com",
                "hashed_password": "hash-b",
            },
        ]
    )

    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "INSERT INTO users" in sql
    assert "ON CONFLICT (email) DO UPDATE" in sql


async def test_increment_used_tokens_executes_atomic_update_returns_none(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    user_id = uuid.uuid4()

    await repo.increment_used_tokens(user_id=user_id, amount=5)

    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE users SET used_tokens=" in sql
    assert "users.used_tokens +" in sql


async def test_try_increment_used_tokens_with_limit_returns_true_when_row_updated(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    user_id = uuid.uuid4()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = user_id
    session.execute.return_value = result_proxy

    result = await repo.try_increment_used_tokens_with_limit(user_id=user_id, amount=5)

    assert result is True
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE users SET used_tokens=" in sql
    assert "RETURNING users.id" in sql


async def test_try_increment_used_tokens_with_limit_returns_false_when_no_row_updated(
    repo_ctx: tuple[UserRepository, AsyncMock],
) -> None:
    repo, session = repo_ctx
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = None
    session.execute.return_value = result_proxy

    result = await repo.try_increment_used_tokens_with_limit(
        user_id=uuid.uuid4(),
        amount=5,
    )

    assert result is False
