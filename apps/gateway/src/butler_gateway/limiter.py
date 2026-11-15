"""账户级限流器（A1-01 §4 组件链 Router → Limiter）：保护账户不被并发打爆。

- M1 最小集 = 每账户并发上限（asyncio.Semaphore）；默认 1（保守，风控优先），
  账户可按数据覆写（overrides）——策略是数据不是分支（A2-02 §3 同款判据）
- 账户间互不阻塞；同账户超限的调用方排队等待
- ⚠️ 不可重入：同账户嵌套 slot 在并发 1 时自我死锁（Semaphore 语义）——
  G5 调用方一次请求持一个槽，不得嵌套；需要嵌套就显式覆写上限
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

DEFAULT_CONCURRENCY = 1


class AccountLimiter:
    """每账户并发闸门：``slot(account_id)`` 异步上下文内持有一个并发槽。"""

    def __init__(
        self,
        *,
        default_concurrency: int = DEFAULT_CONCURRENCY,
        overrides: dict[str, int] | None = None,
    ) -> None:
        if default_concurrency < 1:
            raise ValueError("并发上限不得 < 1（红线 5：非法配置显式报错）")
        self._default = default_concurrency
        self._overrides = dict(overrides or {})
        for account, cap in self._overrides.items():
            if cap < 1:
                raise ValueError(f"账户 {account} 并发覆写非法: {cap}（须 ≥ 1）")
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._held: dict[str, int] = {}  # 各账户当前持锁数（观测面数据源）

    def _sem_for(self, account_id: str) -> asyncio.Semaphore:
        sem = self._sems.get(account_id)
        if sem is None:
            cap = self._overrides.get(account_id, self._default)
            sem = asyncio.Semaphore(cap)
            self._sems[account_id] = sem
        return sem

    @property
    def in_use(self) -> dict[str, int]:
        """观测面：各账户当前持锁数（>0 才出现；/health 可观测用，非热路径）。"""
        return dict(self._held)

    @asynccontextmanager
    async def slot(self, account_id: str) -> AsyncIterator[None]:
        sem = self._sem_for(account_id)
        await sem.acquire()
        self._held[account_id] = self._held.get(account_id, 0) + 1
        try:
            yield
        finally:
            remaining = self._held[account_id] - 1
            if remaining > 0:
                self._held[account_id] = remaining
            else:
                self._held.pop(account_id, None)  # 归零即摘键，不留 0 值残留
            sem.release()
