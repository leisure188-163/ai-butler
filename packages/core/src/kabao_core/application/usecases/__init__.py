"""用例层：跨端编排唯一入口（R6）——按用例边界分包（conventions/04 §2.3，2026-11-14）。

- execute_action：ExecuteAction / RunRequest / 幂等键 / 时间预算 / dry_run 硬承诺（A2-01 §3）
- health_scan：ScanCredentialExpiry / AssessAccountHealth（L0 底座，A4-01 §1~2）
- register_account：RegisterAccount（名册，A2-01 §1）
- list_pending：ListPending（待处理聚合，A3-01）
- collect_usage：CollectUsage / CollectOutcome（R2 用量采集）

本文件 = 纯再导出（聚合器只做装配）：引用方 `from kabao_core.application.usecases
import X` 零改动。ProvisionRequest 是 ports 类型的历史透传（engine 侧测试经此导入），
保留兼容——新增引用请直接从 application.ports 导入。
"""

from kabao_core.application.ports import ProvisionRequest

from kabao_core.application.usecases.collect_usage import CollectOutcome, CollectUsage
from kabao_core.application.usecases.execute_action import (
    DryRunNotSupported,
    ExecuteAction,
    InvalidRequest,
    RunRequest,
    UnsupportedAction,
    idempotency_key,
)
from kabao_core.application.usecases.health_scan import (
    AssessAccountHealth,
    ScanCredentialExpiry,
)
from kabao_core.application.usecases.list_pending import ListPending
from kabao_core.application.usecases.register_account import RegisterAccount

__all__ = [
    "AssessAccountHealth",
    "CollectOutcome",
    "CollectUsage",
    "DryRunNotSupported",
    "ExecuteAction",
    "InvalidRequest",
    "ListPending",
    "ProvisionRequest",
    "RegisterAccount",
    "RunRequest",
    "ScanCredentialExpiry",
    "UnsupportedAction",
    "idempotency_key",
]
