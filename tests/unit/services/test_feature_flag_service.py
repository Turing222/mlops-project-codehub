"""Feature flag service unit tests.

职责：验证标志解析与默认值；边界：mock GrowthBook/httpx；副作用：无。
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from backend.models.orm.user import User
from backend.services.feature_flag_service import FeatureFlagService


@pytest.fixture
def feature_flag_service() -> FeatureFlagService:
    return FeatureFlagService(
        growthbook_api_host="https://cdn.growthbook.io",
        growthbook_sdk_key="sdk-dummy-key-for-development",
        app_env="test",
        beta_user_email_whitelist={"admin@example.com", "tester@dewflow.com"},
        beta_user_phone_whitelist={"13800138000"},
    )


async def test_get_system_features_default(
    feature_flag_service: FeatureFlagService,
) -> None:
    """验证默认状态下匿名系统标志的正常决策。"""
    features = await feature_flag_service.get_system_features()
    assert features["enable-public-registration"] is True
    assert features["enable-closed-beta-login"] is False
    assert features["enable-password-login"] is False


@pytest.mark.parametrize(
    ("app_env", "expected"),
    [
        ("local", True),
        ("smoke", True),
        ("test", True),
        ("prod", False),
        ("production", False),
    ],
)
async def test_public_registration_default_fails_closed_in_production(
    app_env: str, expected: bool
) -> None:
    """验证云端未定义该 flag 时，只有生产环境默认关闭公开注册。"""
    service = FeatureFlagService(
        growthbook_api_host="https://cdn.growthbook.io",
        growthbook_sdk_key="sdk-dummy-key-for-development",
        app_env=app_env,
        beta_user_email_whitelist=set(),
        beta_user_phone_whitelist=set(),
    )

    features = await service.get_system_features()

    assert features["enable-public-registration"] is expected


async def test_get_user_features_regular_user(
    feature_flag_service: FeatureFlagService,
) -> None:
    """验证普通用户默认开启像素头像，但限制积分与思考追踪面板的特征属性决策。"""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "regular_user"
    user.email = "regular@example.com"
    user.is_superuser = False
    user.is_active = True

    flags = await feature_flag_service.get_user_features(user)
    assert flags["enable-pixel-avatar"] is True
    assert flags["enable-credits"] is False
    assert flags["enable-agent-trace"] is False
    assert flags["chat-explicit-retry"] is False


async def test_get_user_features_superuser(
    feature_flag_service: FeatureFlagService,
) -> None:
    """验证超级管理员默认获得像素头像、积分卡片以及思考追踪面板的全功能测试权限。"""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "super_user"
    user.email = "admin@example.com"
    user.is_superuser = True
    user.is_active = True

    flags = await feature_flag_service.get_user_features(user)
    assert flags["enable-pixel-avatar"] is True
    assert flags["enable-credits"] is True
    assert flags["enable-agent-trace"] is True
    assert flags["chat-explicit-retry"] is False


def test_is_beta_user_superuser(feature_flag_service: FeatureFlagService) -> None:
    """超级管理员始终属于内测白名单。"""
    user = MagicMock(spec=User)
    user.is_superuser = True
    user.email = "anyone@example.com"
    user.phone = None
    assert feature_flag_service.is_beta_user(user) is True


def test_is_beta_user_email_in_whitelist(
    feature_flag_service: FeatureFlagService,
) -> None:
    """邮箱在白名单内的普通用户通过内测校验。"""
    user = MagicMock(spec=User)
    user.is_superuser = False
    user.email = "admin@example.com"
    user.phone = None
    assert feature_flag_service.is_beta_user(user) is True


def test_is_beta_user_phone_in_whitelist(
    feature_flag_service: FeatureFlagService,
) -> None:
    """手机号在白名单内的仅手机注册用户通过内测校验。"""
    user = MagicMock(spec=User)
    user.is_superuser = False
    user.email = None
    user.phone = "13800138000"
    assert feature_flag_service.is_beta_user(user) is True


def test_is_beta_user_phone_only_not_in_whitelist(
    feature_flag_service: FeatureFlagService,
) -> None:
    """仅手机注册且手机号不在白名单的用户无法通过内测校验。"""
    user = MagicMock(spec=User)
    user.is_superuser = False
    user.email = None
    user.phone = "19999999999"
    assert feature_flag_service.is_beta_user(user) is False


def test_is_beta_user_neither_email_nor_phone_in_whitelist(
    feature_flag_service: FeatureFlagService,
) -> None:
    """邮箱和手机号均不在白名单的普通用户无法通过内测校验。"""
    user = MagicMock(spec=User)
    user.is_superuser = False
    user.email = "random@example.com"
    user.phone = "19999999999"
    assert feature_flag_service.is_beta_user(user) is False


def test_eval_flag_missing_key_returns_fallback(
    feature_flag_service: FeatureFlagService,
) -> None:
    """云端未定义的 flag 走代码降级默认值。"""
    from growthbook import GrowthBook

    gb = GrowthBook(attributes={}, features={})
    assert FeatureFlagService._eval_flag(gb, "nonexistent", {}, True) is True
    assert FeatureFlagService._eval_flag(gb, "nonexistent", {}, False) is False


def test_eval_flag_existing_key_uses_growthbook_sdk() -> None:
    """云端已定义的 flag 走 GrowthBook SDK 判定。"""
    from growthbook import GrowthBook

    features = {
        "enable-pixel-avatar": {"defaultValue": False},
        "enable-credits": {"defaultValue": True},
    }
    gb = GrowthBook(attributes={}, features=features)

    assert (
        FeatureFlagService._eval_flag(gb, "enable-pixel-avatar", features, True)
        is False
    )
    assert FeatureFlagService._eval_flag(gb, "enable-credits", features, False) is True


# 断路器（CDN 持续故障时熔断，跳过拉取沿用本地缓存）


class _FakeFailingGrowthBookClient:
    """模拟 GrowthBook CDN 客户端持续失败。"""

    def __init__(self) -> None:
        self.calls = 0

    async def get(self, url: str, timeout: float | None = None) -> object:
        self.calls += 1
        raise httpx.ConnectError("cdn down")

    async def aclose(self) -> None:
        pass


def _live_service() -> FeatureFlagService:
    # 非 dummy key 才会真正触发 CDN 拉取
    return FeatureFlagService(
        growthbook_api_host="https://cdn.growthbook.io",
        growthbook_sdk_key="sdk-live-key",
        app_env="test",
        beta_user_email_whitelist=set(),
        beta_user_phone_whitelist=set(),
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=60,
    )


async def test_growthbook_circuit_breaker_opens_after_failures() -> None:
    service = _live_service()
    fake = _FakeFailingGrowthBookClient()
    service._http_client = fake  # type: ignore[assignment]

    # 缓存为空时每次都尝试拉取，连续失败累加计数
    for _ in range(2):
        assert await service._ensure_features_loaded() == {}
    assert fake.calls == 2

    # 阈值后断路器打开：跳过 CDN 拉取，直接沿用本地缓存
    assert await service._ensure_features_loaded() == {}
    assert fake.calls == 2


async def test_growthbook_circuit_breaker_recovers_after_cooldown() -> None:
    service = FeatureFlagService(
        growthbook_api_host="https://cdn.growthbook.io",
        growthbook_sdk_key="sdk-live-key",
        app_env="test",
        beta_user_email_whitelist=set(),
        beta_user_phone_whitelist=set(),
        circuit_breaker_failure_threshold=2,
        circuit_breaker_cooldown_seconds=0,
    )

    class _FlakyClient:
        def __init__(self) -> None:
            self.calls = 0
            self.fail = True

        async def get(self, url: str, timeout: float | None = None) -> object:
            self.calls += 1
            if self.fail:
                raise httpx.ConnectError("cdn down")
            return SimpleNamespace(
                status_code=200,
                json=lambda: {
                    "features": {"enable-rag-rerank": {"defaultValue": True}}
                },
            )

    flaky = _FlakyClient()
    service._http_client = flaky  # type: ignore[assignment]

    for _ in range(2):
        await service._ensure_features_loaded()
    assert service._circuit._state.value == "open"

    # cooldown=0：下次进入半开放行探测，探测成功即恢复闭合
    flaky.fail = False
    features = await service._ensure_features_loaded()
    assert "enable-rag-rerank" in features
    assert service._circuit._state.value == "closed"
