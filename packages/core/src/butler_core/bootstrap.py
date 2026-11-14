"""组装根：五业务域用例的统一装配入口（A1-05 §2）。

只认端口协议，零框架依赖；engine.bridge 传入具体适配器。跨域编排在这里组合，
域与域之间互不 import（依赖恒等式由测试钉死）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.usecases.register_account import RegisterAccount
from butler_core.execution.domain import ActionKind
from butler_core.execution.ports import (
    PortSelector,
    ProvisionPort,
    RunLedger,
    routing_ports,
)
from butler_core.execution.usecases.execute_action import ExecuteAction
from butler_core.scheduling.usecases.list_pending import ListPending
from butler_core.shared.events import EventSink
from butler_core.usage.ports import UsagePort, UsageStore
from butler_core.usage.usecases.collect_usage import CollectUsage


@dataclass(frozen=True)
class Kit:
    """五域装配产物：端/engine 只消费这一组用例对象。"""

    execute_action: ExecuteAction
    register_account: RegisterAccount
    list_pending: ListPending
    collect_usage: CollectUsage


def build_kit(
    *,
    ledger: RunLedger,
    sink: EventSink,
    accounts: AccountRepository,
    usage_store: UsageStore,
    ports: Mapping[ActionKind, ProvisionPort] | PortSelector | None = None,
    usage_ports: Mapping[str, UsagePort] | None = None,
    limit: int = 50,
) -> Kit:
    selector = ports if callable(ports) else routing_ports(ports or {}, {})
    return Kit(
        execute_action=ExecuteAction(ledger=ledger, sink=sink, ports=selector),
        register_account=RegisterAccount(accounts=accounts),
        list_pending=ListPending(ledger=ledger, limit=limit),
        collect_usage=CollectUsage(
            ports=usage_ports or {}, store=usage_store, sink=sink
        ),
    )


def execute_action(
    ledger: RunLedger,
    sink: EventSink,
    ports: Mapping[ActionKind, ProvisionPort] | PortSelector | None = None,
) -> ExecuteAction:
    """兼容旧装配形态：只装执行用例。"""

    selector = ports if callable(ports) else routing_ports(ports or {}, {})
    return ExecuteAction(ledger=ledger, sink=sink, ports=selector)


def register_account(accounts: AccountRepository) -> RegisterAccount:
    return RegisterAccount(accounts=accounts)


def list_pending(ledger: RunLedger, limit: int = 50) -> ListPending:
    return ListPending(ledger=ledger, limit=limit)
