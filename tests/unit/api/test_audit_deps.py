"""Audit dependency provider unit tests.

职责：验证 audit request context 使用可信代理解析后的客户端 IP；边界：不连接数据库；副作用：临时替换 resolver。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from backend.api.deps import audit
from backend.core.client_ip import ClientIPResolver


def test_get_audit_service_uses_resolved_client_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_client_ip_resolver",
        ClientIPResolver("127.0.0.1/32"),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/login",
            "headers": [(b"x-real-ip", b"203.0.113.10")],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
            "scheme": "http",
            "app": SimpleNamespace(
                state=SimpleNamespace(session_factory=SimpleNamespace())
            ),
        }
    )

    service = audit.get_audit_service(request=request, uow=SimpleNamespace())

    assert service.request_context.ip == "203.0.113.10"
