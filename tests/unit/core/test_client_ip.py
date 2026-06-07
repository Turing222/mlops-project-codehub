"""Client IP resolver unit tests.

职责：验证可信代理下的 X-Real-IP 解析与非可信来源回退；边界：纯逻辑测试；副作用：无。
"""

from backend.core.client_ip import ClientIPResolver


def test_trusted_proxy_uses_valid_x_real_ip() -> None:
    resolver = ClientIPResolver("172.30.0.10/32")

    assert resolver.resolve("172.30.0.10", "203.0.113.10") == "203.0.113.10"


def test_untrusted_peer_ignores_x_real_ip() -> None:
    resolver = ClientIPResolver("172.30.0.10/32")

    assert resolver.resolve("172.30.0.11", "203.0.113.10") == "172.30.0.11"


def test_trusted_proxy_ignores_invalid_x_real_ip() -> None:
    resolver = ClientIPResolver("172.30.0.10/32")

    assert resolver.resolve("172.30.0.10", "invalid") == "172.30.0.10"


def test_missing_peer_returns_unknown() -> None:
    resolver = ClientIPResolver("172.30.0.10/32")

    assert resolver.resolve(None, "203.0.113.10") == "unknown"
