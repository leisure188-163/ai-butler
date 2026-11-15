"""路由表来源（R4-G6 热装载，ADR-012 裁决 6 演进）：server 契约为真相，文件兜底。

- 真相源 = server ``GET /api/v1/gateway/routes``（裁决 2：主控通信 HTTP 复用
  契约；裁决 6：规则 server 管、网关只读）——server 可达即采纳（含空表：
  管理面清空 = 如实清空，不拿旧文件顶回来）
- 文件 = 启动兜底（server 未起/不可达时保持最近已知表；初始 = 数据根
  gateway-routes.json，无 server 环境 = 纯文件模式照常工作）
- TTL 窗口内复用上次结果（主控探测同款语义）；刷新失败不回滚已采纳表
  （坏消息不是消息——保持最近已知好表，等待下次窗口）
- 时钟可注入（测试假时钟）；``refresh()`` 返回来源如实分列
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from butler_core.execution.gateway_routes import RouteTable

DEFAULT_ROUTES_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class RoutesSnapshot:
    """一次路由表状态：表 + 来源（/health 观测面与日志用）。"""

    table: RouteTable
    source: str  # server / file / server_fallback（刷新失败沿用上次 server 表）
    fetched_at: float  # monotonic


class RoutesSource:
    """路由表热装载源：TTL 拉取 server 契约，文件兜底，最近已知好表保值。"""

    def __init__(
        self,
        *,
        fetch_from_server: Callable[[], Awaitable[RouteTable | None]],
        file_table: RouteTable,
        ttl_seconds: float = DEFAULT_ROUTES_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch_from_server
        self._file_table = file_table
        self._ttl = ttl_seconds
        self._clock = clock
        self._snapshot = RoutesSnapshot(
            table=file_table, source="file", fetched_at=clock()
        )

    @property
    def snapshot(self) -> RoutesSnapshot:
        return self._snapshot

    def table(self) -> RouteTable:
        """当前生效路由表（调用方免判空——空表也是合法表）。"""
        return self._snapshot.table

    async def refresh(self) -> RoutesSnapshot:
        """TTL 过期则拉 server；窗口内直接返回当前快照（热路径零开销）。"""
        now = self._clock()
        if now - self._snapshot.fetched_at < self._ttl:
            return self._snapshot
        fetched = await self._fetch()
        if fetched is not None:
            self._snapshot = RoutesSnapshot(
                table=fetched, source="server", fetched_at=now
            )
            return self._snapshot
        # server 不可达/非法：保持最近已知表（文件初始态或上次 server 表）
        source = (
            "server_fallback" if self._snapshot.source == "server" else self._snapshot.source
        )
        self._snapshot = RoutesSnapshot(
            table=self._snapshot.table, source=source, fetched_at=now
        )
        return self._snapshot
