"""G3 限流器：每账户并发闸门（A1-01 §4 Router → Limiter 链）。

- 默认并发 1（保守，风控优先）；overrides = 数据覆写，不是分支
- pytest 无 asyncio 插件：异步场景用 asyncio.run() 包同步测试
"""

from __future__ import annotations

import asyncio

import pytest

from butler_gateway.limiter import AccountLimiter


def test_serializes_same_account_by_default() -> None:
    """默认并发 1：同账户两个 worker 严格串行（M1 保守默认）。"""
    limiter = AccountLimiter()
    events: list[str] = []

    async def scenario() -> None:
        async def worker(tag: str) -> None:
            async with limiter.slot("acct"):
                events.append(f"enter-{tag}")
                await asyncio.sleep(0.01)
                events.append(f"exit-{tag}")

        await asyncio.gather(worker("a"), worker("b"))

    asyncio.run(scenario())
    assert events == ["enter-a", "exit-a", "enter-b", "exit-b"]


def test_override_cap_allows_parallel_within_account() -> None:
    """并发 2：同账户两 worker 同时进入——上限是数据覆写的结果。"""
    limiter = AccountLimiter(overrides={"acct": 2})
    entered: list[str] = []

    async def scenario() -> None:
        async def worker(tag: str) -> None:
            async with limiter.slot("acct"):
                entered.append(tag)
                await asyncio.sleep(0.01)

        await asyncio.gather(worker("a"), worker("b"))

    asyncio.run(scenario())
    assert sorted(entered) == ["a", "b"]


def test_third_caller_queues_when_cap_reached() -> None:
    """并发 2：第 3 个调用方排队等待，不超限不丢失。"""
    limiter = AccountLimiter(overrides={"acct": 2})
    state = {"current": 0, "peak": 0}

    async def scenario() -> None:
        async def worker() -> None:
            async with limiter.slot("acct"):
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
                await asyncio.sleep(0.01)
                state["current"] -= 1

        await asyncio.gather(*[worker() for _ in range(5)])

    asyncio.run(scenario())
    assert state["peak"] == 2


def test_accounts_independent() -> None:
    """不同账户互不阻塞：默认并发 1 下两账户各自推进、同轮完成。"""
    limiter = AccountLimiter()
    finished: list[str] = []

    async def scenario() -> None:
        async def worker(acct: str) -> None:
            async with limiter.slot(acct):
                await asyncio.sleep(0.01)
                finished.append(acct)

        await asyncio.gather(worker("x"), worker("y"))

    asyncio.run(scenario())
    assert sorted(finished) == ["x", "y"]


def test_in_use_observability() -> None:
    """观测面：持锁数随 enter/exit 精确增减，归零摘键不留 0 值残留。

    cap 1 时同账户嵌套 slot = 自我死锁（Semaphore 语义，不可重入），
    嵌套场景须显式覆写并发上限——这本身就是 G5 调用方的约束。
    """
    limiter = AccountLimiter(overrides={"acct": 2})
    assert limiter.in_use == {}

    async def scenario() -> None:
        async with limiter.slot("acct"):
            assert limiter.in_use == {"acct": 1}
            async with limiter.slot("acct"):
                assert limiter.in_use == {"acct": 2}
            assert limiter.in_use == {"acct": 1}
        assert limiter.in_use == {}  # 不残留 {"acct": 0}

    asyncio.run(scenario())


def test_invalid_config_rejected() -> None:
    """红线 5：并发上限 < 1 属非法配置，构造即拒绝。"""
    with pytest.raises(ValueError, match="并发"):
        AccountLimiter(default_concurrency=0)
    with pytest.raises(ValueError, match="并发"):
        AccountLimiter(overrides={"acct": 0})
