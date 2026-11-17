"""执行域端口（A2-05 §3）：能力申报 / 动作执行 / Run 台账 / 端口路由。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from butler_core.execution.domain import Action, ActionKind, Run, RunResult
from butler_core.execution.gateway_routes import RouteTable

__all__ = [
    "Capabilities",
    "GatewayRoutesStore",
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
    account_code: str = "main"


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


class GatewayRoutesStore(Protocol):
    """网关路由表存储端口（R4-G6，ADR-012 裁决 6）：server 管、网关只读。

    实现 = 数据根 JSON 文件（网关 M1 启动时装载的唯一规则源）；校验单源在
    RouteTable.from_dict（core），存储实现只管文件 IO 与原子性。
    """

    def load(self) -> RouteTable:
        """装载当前路由表；文件缺失 = 空表合法初始态；非法 = 显式 ValueError。"""
        ...

    def save(self, table: RouteTable) -> None:
        """整表替换落盘（声明式配置，无增量 PATCH）；原子写防半截文件。"""
        ...
