import pytest

@pytest.mark.asyncio
async def test_get_user_service(mocker):
    # 1. 模拟 Repository 的返回值
    mock_repo = mocker.patch("services.user_service.UserRepository.get_by_id")
    mock_repo.return_value = {"id": 1, "name": "Fake User"}
    
    # 2. 调用 Service 方法
    from services.user_service import UserService
    service = UserService()
    user = await service.get_user(1)
    
    # 3. 断言
    assert user["name"] == "Fake User"
    mock_repo.assert_called_once_with(1)