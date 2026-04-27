import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(monkeypatch):
    # Ensure test-safe settings before importing app/config.
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
