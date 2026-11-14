"""执行域端口（A2-05 §3）：能力申报 / 动作执行 / Run 台账 / 端口路由。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from butler_core.execution.domain import Action, ActionKind, Run, RunResult

__all__ = [
    "Capabilities",
    "PortSelector",
    "ProvisionPort",
    "ProvisionRequest",
    "RunLedger",
    "routing_ports",
]


@dataclass(frozen=True)
class Capabilities:
    """能力如实申报：签名里没有的 = 申报不支持 → 用例层拒绝。"""

    dry_run: bool = False
    multi_account: bool = False
    idempotency_window: str | None = None


@dataclass(frozen=True)
class ProvisionRequest:
    """端口入参：deadline 是时间预算的硬边界。"""

    kind: ActionKind
    target: str
    account_id: str
    params: Mapping[str, str]
    deadline: datetime
    dry_run: bool = False
    account_key: str = "main"


class ProvisionPort(Protocol):
    """领取类端口：适配器不做语义决策、不解析日志、不维护映射表。"""

    def capabilities(self) -> Capabilities: ...

    def run(self, req: ProvisionRequest) -> RunResult: ...


PortSelector = Callable[[Action], "ProvisionPort | None"]


def routing_ports(
    kind_ports: Mapping[ActionKind, ProvisionPort],
    target_ports: Mapping[str, ProvisionPort],
) -> PortSelector:
    """target 精确匹配优先，kind 兜底（ADR-005）。"""

    def select(action: Action) -> ProvisionPort | None:
        return target_ports.get(action.target) or kind_ports.get(action.kind)

    return select


class RunLedger(ABC):
    """Run 台账端口：SQL 只在 engine 适配器（A4-01 §5）。"""

    @abstractmethod
    def save(self, run: Run) -> None: ...

    @abstractmethod
    def find_by_idempotency_key(self, key: str) -> Run | None: ...

    @abstractmethod
    def list_for_account(self, account_id: str, *, limit: int) -> list[Run]: ...

    @abstractmethod
    def list_recent(self, *, limit: int) -> list[Run]: ...
