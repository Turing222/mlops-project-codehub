"""Service dependency provider unit tests.

职责：验证 API service provider 将 web settings 正确传入 service；边界：不连接真实 Redis / DB；副作用：临时 monkeypatch 模块变量。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.api.deps import services


def test_get_sms_service_uses_web_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings = SimpleNamespace(
        SMS_CODE_EXPIRE_SECONDS=111,
        SMS_CODE_RATE_LIMIT_SECONDS=22,
        SMS_MOCK_MODE=True,
        SMS_VERIFY_FAILURE_LIMIT=3,
        SMS_VERIFY_FAILURE_WINDOW_SECONDS=44,
        SMS_VERIFY_LOCKOUT_SECONDS=55,
    )
    monkeypatch.setattr(services, "get_web_settings", lambda: fake_settings)

    service = services.get_sms_service()

    assert service._sms_code_expire_seconds == 111
    assert service._sms_code_rate_limit_seconds == 22
    assert service._sms_mock_mode is True
    assert service._sms_verify_failure_limit == 3
    assert service._sms_verify_failure_window_seconds == 44
    assert service._sms_verify_lockout_seconds == 55
