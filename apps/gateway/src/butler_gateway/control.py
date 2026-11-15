"""主控通信（ADR-012 裁决 2：HTTP localhost，复用 server 契约 API，不发明新 IPC）。

G1 范围 = 可达性观测（拉 server ``GET /health``）；G6 热装载扩路由契约拉取
（``fetch_routes``）——同一 client、同一注入纪律。

transport 可注入（测试用 httpx.MockTransport，不碰真网络）——与 engine
Windows 凭据适配器的 api_factory 注入先例同构。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from butler_core.execution.gateway_routes import RouteTable

PING_TTL_SECONDS = 30.0  # /health 惰性刷新窗口：窗口内复用上次探测结果
PING_TIMEOUT_SECONDS = 2.0
ROUTES_TIMEOUT_SECONDS = 3.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ControlProbe:
    """一次主控探测的快照（如实记录，失败也是事实）。"""

    server_url: str
    reachable: bool
    latency_ms: float | None
    checked_at: str
    error: str | None = None


class ControlClient:
    """主控 HTTP client：带 TTL 缓存的可达性探测。"""

    def __init__(
        self,
        server_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        ttl: float = PING_TTL_SECONDS,
        timeout: float = PING_TIMEOUT_SECONDS,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout)
        self._ttl = ttl
        self._last: ControlProbe | None = None
        self._last_monotonic = 0.0

    async def probe(self, *, force: bool = False) -> ControlProbe:
        """探测主控可达性；TTL 窗口内复用上次结果（force 强制刷新）。"""
        if (
            not force
            and self._last is not None
            and time.monotonic() - self._last_monotonic < self._ttl
        ):
            return self._last
        started = time.perf_counter()
        try:
            resp = await self._client.get(f"{self._server_url}/health")
            resp.raise_for_status()
            probe = ControlProbe(
                server_url=self._server_url,
                reachable=True,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
                checked_at=_now_iso(),
            )
        except (httpx.HTTPError, OSError) as exc:
            probe = ControlProbe(
                server_url=self._server_url,
                reachable=False,
                latency_ms=None,
                checked_at=_now_iso(),
                error=f"{type(exc).__name__}: {exc}",
            )
        self._last = probe
        self._last_monotonic = time.monotonic()
        return probe

    async def fetch_routes(self) -> RouteTable | None:
        """拉 server 路由契约；不可达/响应非法返回 None（来源层如实保值，不猜）。"""
        try:
            resp = await self._client.get(
                f"{self._server_url}/api/v1/gateway/routes",
                timeout=ROUTES_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return RouteTable.from_dict(resp.json())
        except (httpx.HTTPError, OSError, ValueError):
            return None

    async def aclose(self) -> None:
        await self._client.aclose()
