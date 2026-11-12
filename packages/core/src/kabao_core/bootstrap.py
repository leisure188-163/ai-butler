"""组装根：CLI / server 统一从这里取用例对象（传入各自适配器）。

ADR-001 落地后（packages/engine），engine.bridge 调用这里的工厂并传入具体适配器；
bootstrap 只认端口协议，保持 core 纯净。端不再 import 本模块（统一走 bridge）。
ADR-003：连接器 target 级端口经 EngineKit.register_provision_ports 动态挂载，
本文件只做兼容映射 → 选择器的包装。
"""

from typing import Mapping

from kabao_core.application.ports import (
    AccountRepository,
    EventSink,
    PortSelector,
    ProvisionPort,
    RunLedger,
    routing_ports,
)
from kabao_core.application.usecases import (
    ExecuteAction,
    ListPending,
    RegisterAccount,
)
from kabao_core.domain.action import ActionKind


def execute_action(
    ledger: RunLedger,
    sink: EventSink,
    ports: Mapping[ActionKind, ProvisionPort] | PortSelector | None = None,
) -> ExecuteAction:
    """动作编排用例装配：kind 映射（兼容形态）或选择器均可。"""
    selector = ports if callable(ports) else routing_ports(ports or {}, {})
    return ExecuteAction(ledger=ledger, sink=sink, ports=selector)


def register_account(accounts: AccountRepository) -> RegisterAccount:
    return RegisterAccount(accounts=accounts)


def list_pending(ledger: RunLedger, limit: int = 50) -> ListPending:
    return ListPending(ledger=ledger, limit=limit)
