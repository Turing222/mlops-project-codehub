import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app  # 导入你的 FastAPI 实例


@pytest.fixture
async def client():
    # 使用 ASGITransport 直接调用 app，无需启动真实服务器，速度极快
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def mock_user_repo(mocker):
    # 创建一个异步 Mock 实例
    mock = mocker.AsyncMock()
    # 设置默认行为
    mock.get_by_id.return_value = {"id": 1, "username": "test_user"}
    return mock
