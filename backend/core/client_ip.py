"""Trusted proxy-aware client IP resolution.

职责：从直接 peer 与受信任代理提供的 X-Real-IP 中解析客户端地址；边界：不依赖 FastAPI；副作用：无。
"""

from __future__ import annotations

import ipaddress


class ClientIPResolver:
    """Resolve client IPs without trusting headers from arbitrary peers."""

    def __init__(self, trusted_proxy_cidrs: str = "") -> None:
        self._trusted_proxy_networks = self._parse_cidr_list(trusted_proxy_cidrs)

    def resolve(self, peer_ip: str | None, x_real_ip: str | None = None) -> str:
        normalized_peer_ip = (peer_ip or "").strip()
        if normalized_peer_ip and self._is_trusted_proxy(normalized_peer_ip):
            normalized_real_ip = (x_real_ip or "").strip()
            if self._is_valid_ip(normalized_real_ip):
                return normalized_real_ip
        return normalized_peer_ip or "unknown"

    def _is_trusted_proxy(self, peer_ip: str) -> bool:
        if not self._trusted_proxy_networks:
            return False
        try:
            ip_address = ipaddress.ip_address(peer_ip)
        except ValueError:
            return False
        return any(ip_address in network for network in self._trusted_proxy_networks)

    @staticmethod
    def _is_valid_ip(value: str) -> bool:
        if not value:
            return False
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def _parse_cidr_list(
        raw_cidrs: str,
    ) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        cidr_items = [item.strip() for item in raw_cidrs.split(",") if item.strip()]
        return [ipaddress.ip_network(item, strict=False) for item in cidr_items]
