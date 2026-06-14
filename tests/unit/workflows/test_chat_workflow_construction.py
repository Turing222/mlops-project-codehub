"""Chat workflow construction test — verifies lightweight wiring with test doubles.

职责：验证聊天 workflow 可用测试替身完成轻量构造；边界：不启动 HTTP stack、worker 或真实外部依赖；副作用：无。
"""

from unittest.mock import AsyncMock, MagicMock

from backend.application.chat.web_stream_workflow import ChatWorkflow
from backend.services.feature_flag_service import (
    _AI_SYSTEM_FLAG_DEFAULTS,
    FeatureFlagService,
)


def _make_mock_feature_flag_service(
    overrides: dict[str, bool] | None = None,
) -> AsyncMock:
    flags = {
        **_AI_SYSTEM_FLAG_DEFAULTS,
        "enable-public-registration": True,
        "enable-closed-beta-login": False,
        **(overrides or {}),
    }
    svc = AsyncMock(spec=FeatureFlagService)
    svc.get_system_features = AsyncMock(return_value=flags)
    return svc


def test_minimal_workflow_construction() -> None:
    uow = MagicMock()
    dispatcher = AsyncMock()
    redis_client = AsyncMock()
    permission_service = MagicMock()
    feature_flag_service = _make_mock_feature_flag_service()
    workflow = ChatWorkflow(
        uow, dispatcher, redis_client, permission_service, feature_flag_service
    )

    assert workflow is not None
