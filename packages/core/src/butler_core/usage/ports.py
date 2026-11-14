"""用量域端口（A2-06 §3）：采集通道 / 时序存储 / 请求形状。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from butler_core.shared.errors import DomainError
from butler_core.shared.ids import new_id  # 兼容旧调用形态
from butler_core.usage.domain import (
    QuotaLedgerEntry,
    UsageAggregate,
    UsageResult,
    UsageSnapshot,
)

__all__ = [
    "UsagePort",
    "UsageRequest",
    "UsageRequestInvalid",
    "UsageResult",
    "UsageStore",
    "new_id",
]


class UsageRequestInvalid(DomainError):
    """UsageRequest 形状非法（target / account_id 空白）。"""


@dataclass(frozen=True)
class UsageRequest:
    target: str
    account_id: str
    deadline: datetime
    account_key: str = "main"

    def __post_init__(self) -> None:
        if not self.target.strip() or not self.account_id.strip():
            raise UsageRequestInvalid("UsageRequest 需要非空 target 与 account_id")


class UsagePort(Protocol):
    """采集端口：适配器取数并归一，不做语义决策 / 不派生指标。"""

    def collect(self, req: UsageRequest) -> UsageResult: ...


class UsageStore(ABC):
    """三实体落库 + 账号维度读取（SQL 只在 engine 适配器）。"""

    @abstractmethod
    def save_snapshot(self, snapshot: UsageSnapshot) -> None: ...

    @abstractmethod
    def list_snapshots(self, account_id: str, *, limit: int) -> list[UsageSnapshot]: ...

    @abstractmethod
    def save_aggregate(self, aggregate: UsageAggregate) -> None: ...

    @abstractmethod
    def latest_aggregate(self, account_id: str) -> UsageAggregate | None: ...

    @abstractmethod
    def append_ledger(self, entries: Iterable[QuotaLedgerEntry]) -> int: ...

    @abstractmethod
    def list_ledger(self, account_id: str, *, limit: int) -> list[QuotaLedgerEntry]: ...
