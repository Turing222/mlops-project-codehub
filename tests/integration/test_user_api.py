import pytest

'''
@pytest.mark.asyncio
async def test_get_user_success(client):
    """测试正常获取存在用户的情况"""
    # 1. 执行：发送 GET 请求
    # 这里的 user_id=1 应该在你的开发数据库或 Mock 数据中存在
    user_id = 1
    response = await client.get(f"/users/{user_id}")

    # 2. 断言：验证返回结果
    assert response.status_code == 200
    
    data = response.json()
    assert data["id"] == user_id
    assert "email" in data  # 验证返回的 JSON 包含关键字段
    assert "username" in data
'''


@pytest.mark.asyncio
async def test_read_users_filter_by_username(client):
    """测试通过 username 查询参数进行过滤"""
    # 假设你的数据库里有一个叫 "admin" 的用户
    search_name = "test2"

    # 这里的 params 会被自动转换为 /users?username=admin
    response = await client.get(
        "/api/v1/users/get_users", params={"username": search_name}
    )

    assert response.status_code == 200
    data = response.json()
    # 验证返回的结果是否符合过滤条件
    for user in data:
        assert search_name in user["username"]
