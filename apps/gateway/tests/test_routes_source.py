"""路由表热装载源测试（R4-G6）：假时钟 + 假拉取，TTL/回退/采纳语义逐条钉死。

pytest 无 asyncio 插件：异步场景用 asyncio.run() 包同步测试（test_limiter 先例）。
"""

from __future__ import annotations

import asyncio

from butler_core.execution.gateway_routes import RouteTable
from butler_gateway.routes_source import RoutesSource

FILE_TABLE = RouteTable.from_dict({"routes": [{"model": "file-m", "accounts": ["a:main"]}]})
SERVER_TABLE = RouteTable.from_dict({"routes": [{"model": "srv-m", "accounts": ["b:main"]}]})


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeFetch:
    def __init__(self, result: RouteTable | None) -> None:
        self.result = result
        self.calls = 0

    async def __call__(self) -> RouteTable | None:
        self.calls += 1
        return self.result


def test_初始_文件兜底态() -> None:
    src = RoutesSource(fetch_from_server=FakeFetch(None), file_table=FILE_TABLE, clock=FakeClock())
    assert src.snapshot.source == "file"
    assert src.table().route("file-m") == ("a:main",)


def test_ttl窗口内_不重复拉取() -> None:
    clock, fetch = FakeClock(), FakeFetch(SERVER_TABLE)
    src = RoutesSource(fetch_from_server=fetch, file_table=FILE_TABLE, clock=clock)

    async def scenario():
        clock.now += 31  # 越过初始快照的 TTL 窗口
        await src.refresh()
        first_calls = fetch.calls
        clock.now += 10  # 窗口内（TTL 30s）
        await src.refresh()
        return first_calls

    assert asyncio.run(scenario()) == 1  # 窗口内复用，零开销
    assert src.snapshot.source == "server"


def test_ttl过期_采纳server真相_含空表() -> None:
    clock, fetch = FakeClock(), FakeFetch(SERVER_TABLE)
    src = RoutesSource(fetch_from_server=fetch, file_table=FILE_TABLE, clock=clock)

    async def scenario():
        clock.now += 31
        await src.refresh()
        clock.now += 31
        fetch.result = RouteTable(rules=())  # 管理面清空 = 真相，如实清空
        return await src.refresh()

    snap = asyncio.run(scenario())
    assert snap.source == "server" and snap.table.rules == ()


def test_server不可达_保持最近已知server表() -> None:
    clock, fetch = FakeClock(), FakeFetch(SERVER_TABLE)
    src = RoutesSource(fetch_from_server=fetch, file_table=FILE_TABLE, clock=clock)

    async def scenario():
        clock.now += 31
        await src.refresh()
        clock.now += 31
        fetch.result = None  # server 掉线
        snap1 = await src.refresh()
        clock.now += 31  # 掉线持续
        snap2 = await src.refresh()
        return snap1, snap2

    snap1, snap2 = asyncio.run(scenario())
    assert snap1.source == "server_fallback"
    assert snap1.table.route("srv-m") == ("b:main",)  # 好表保值，不回滚到文件
    assert snap2.source == "server_fallback" and snap2.table.rules != ()


def test_无server环境_纯文件模式照常() -> None:
    clock, fetch = FakeClock(), FakeFetch(None)
    src = RoutesSource(fetch_from_server=fetch, file_table=FILE_TABLE, clock=clock)

    async def scenario():
        clock.now += 31
        return await src.refresh()

    snap = asyncio.run(scenario())
    assert snap.source == "file" and snap.table.route("file-m") == ("a:main",)
