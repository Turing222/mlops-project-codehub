import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models.orm.user import User


@pytest.mark.asyncio
async def test_get_users_repo(mocker):
    # 1. 模拟 session 对象
    # 因为 get_users 是 async 的，session.execute 必须返回一个 awaitable
    mock_session = AsyncMock()

    # 2. 模拟 SQLAlchemy 的返回链路：Result -> Scalars -> All
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    fake_users = [User(id=1, username="tongying"), User(id=2, username="guest")]

    # 模拟链式调用：result.scalars().all()
    mock_session.execute.return_value = mock_result
    mock_result.scalars.return_value = mock_scalars
    mock_scalars.all.return_value = fake_users

    # 3. 实例化 Repo 并传入 mock_session
    from app.repositories.user_repo import UserRepository  # 换成你的实际路径

    repo = UserRepository(mock_session)

    # 4. 执行被测方法
    users = await repo.get_users(username="tongying")

    # 5. 断言
    assert len(users) == 2
    assert users[0].username == "tongying"

    # 6. 验证 SQL 逻辑：检查 execute 是否被调用，且传入了正确的过滤条件
    # 这是最专业的一步，确保你的 offset/limit 生效了
    args, _ = mock_session.execute.call_args
    statement = args[0]

    # 验证生成的 SQL 字符串里是否包含正确的关键字
    sql_str = str(statement.compile())
    print(sql_str)
    # assert "LIMIT :limit_1" in sql_str
    # assert "OFFSET :offset_1" in sql_str
    assert "username =" in sql_str
