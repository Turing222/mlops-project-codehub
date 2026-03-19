from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from backend.core.config import settings
from backend.core.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)


@pytest.mark.asyncio
async def test_get_password_hash_and_verify_password_round_trip():
    hashed = await get_password_hash("Password123")

    assert hashed != "Password123"
    assert await verify_password("Password123", hashed) is True


@pytest.mark.asyncio
async def test_verify_password_returns_false_for_wrong_password():
    hashed = await get_password_hash("Password123")

    assert await verify_password("WrongPassword123", hashed) is False


@pytest.mark.asyncio
async def test_verify_password_returns_false_for_invalid_hash():
    assert await verify_password("Password123", "not-a-valid-hash") is False


def test_create_access_token_contains_subject_iat_and_exp():
    expires_delta = timedelta(minutes=15)

    token = create_access_token("user-123", expires_delta=expires_delta)
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )

    assert payload["sub"] == "user-123"
    assert "iat" in payload
    assert "exp" in payload

    iat = datetime.fromtimestamp(payload["iat"], UTC)
    exp = datetime.fromtimestamp(payload["exp"], UTC)
    ttl_seconds = (exp - iat).total_seconds()

    assert 14 * 60 <= ttl_seconds <= 15 * 60 + 5
