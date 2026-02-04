import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app  # 导入你的 FastAPI 实例
from backend.models.userb import UserBase
from backend.repositories.user_repo import UserRepository
from backend.core.exceptions import ValidationError
from unittest.mock import ANY
import respx


@pytest.fixture
async def client():
    # 使用 ASGITransport 直接调用 app，无需启动真实服务器，速度极快
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# mock repo
@pytest.fixture
def mock_user_repo(mocker):
    # 使用 autospec=True，如果访问了 Repo 没有的方法或参数不匹配，会直接抛错
    # 假设你定义了抽象基类或具体的 UserRepo 类
    mock = mocker.create_autospec(UserRepository, instance=True)

    # 企业级实践：Mock 返回 Pydantic 模型而非 dict，保持类型一致性
    mock.get_users.return_value = UserBase(
        username="google_dev", email="test@google.com"
    )

    # 模拟异常场景（Side Effect）
    mock.get_users.side_effect = ValidationError()

    return mock


# mock path and file
@pytest.fixture
def test_config_loader(tmp_path):
    # tmp_path 是一个真实的临时目录 (pathlib.Path)
    d = tmp_path / "configs"
    d.mkdir()
    # 文件名字
    f = d / "settings.json"
    # 文件内容写入
    f.write_text('{"db_pool_size": 20}')

    # 运行你的业务逻辑，传入真实的临时路径 直接调用open读取
    # config = load_config(f)
    config = []
    assert config["db_pool_size"] == 20


# mock process called type
@pytest.fixture
def test_order_fulfillment(mocker, mock_email_service):
    # 模拟一个涉及分布式事务的函数
    process_payment = mocker.patch("app.services.payment.process", return_value=True)

    # 执行业务逻辑
    # result = fulfill_order(order_id="ORD-123")
    service = lambda a: a + 10
    service = lambda a, f: f(a.order_id)

    result = service(process_payment)

    # 断言调用细节（Idempotency 幂等性检查常考点）
    process_payment.assert_called_once_with("ORD-123", amount=ANY)
    mock_email_service.send.assert_called_after(process_payment)  # 逻辑顺序校验
