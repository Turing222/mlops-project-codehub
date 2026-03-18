import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(monkeypatch):
    # Ensure test-safe settings before importing app/config.
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    # Avoid accidental env string overrides for Literal[int] fields.
    monkeypatch.delenv("RAG_EMBED_DIM", raising=False)

    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
