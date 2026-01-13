import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app  # 导入你的 FastAPI 实例

@pytest.fixture
async def client():
    # 使用 ASGITransport 直接调用 app，无需启动真实服务器，速度极快
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac