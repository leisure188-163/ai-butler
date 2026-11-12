"""事件模型（A2-01 §5）：L0 通知中心的唯一输入。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping
from uuid import uuid4

from kabao_core.domain.errors import DomainError
from kabao_core.domain.run import Run, now_utc


class Severity(StrEnum):
    """打扰级别（A4-01 §3）：用户可在设置里按事件类型覆盖。"""

    SILENT = "silent"
    BADGE = "badge"
    PUSH = "push"


class EventType(StrEnum):
    """事件类型全集（A2-01 §5）。"""

    RUN_FINISHED = "RUN_FINISHED"  # Run 终态（含 status/kind）：通知、台账、统计的统一入口
    CREDENTIAL_EXPIRING = "CREDENTIAL_EXPIRING"  # 凭据 N 天内到期
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED"
    QUOTA_LOW = "QUOTA_LOW"  # 额度低于阈值（L2 产出）
    PROTOCOL_CHANGED = "PROTOCOL_CHANGED"  # 上游协议变化探测（L7 协议守护）
    ACCOUNT_HEALTH_CHANGED = "ACCOUNT_HEALTH_CHANGED"


@dataclass(frozen=True)
class Event:
    """事件 schema：{id, type, ts, account_id?, severity, payload}。

    id 相对规格是补充：A4-01 §3 要求通知可追溯到 Run/Event id。
    """

    id: str
    type: EventType
    ts: datetime
    severity: Severity
    payload: Mapping[str, str] = field(default_factory=dict)
    account_id: str | None = None

    @classmethod
    def new(
        cls,
        type_: EventType,
        *,
        severity: Severity,
        account_id: str | None = None,
        payload: Mapping[str, str] | None = None,
    ) -> Event:
        return cls(
            id=uuid4().hex,
            type=type_,
            ts=now_utc(),
            severity=severity,
            payload=payload or {},
            account_id=account_id,
        )


def run_finished_event(run: Run) -> Event:
    """RUN_FINISHED 工厂：severity 由谓词在 core 推导（端零映射，红线 2）。

    A2-01 §5 字面规则：全部成功 = silent；只有 is_attention 结果才产生可见通知
    （fail 不主动打扰——细节在台账，行动项在"待处理"）。
    """
    result = run.result
    if result is None:
        raise DomainError(f"Run {run.id} 未到终态，无 RUN_FINISHED 事件")
    severity = Severity.BADGE if result.kind.is_attention else Severity.SILENT
    return Event.new(
        EventType.RUN_FINISHED,
        severity=severity,
        account_id=run.account_id,
        payload={
            "run_id": run.id,
            "status": result.status.value,
            "action": run.action.kind.value,  # 审计订阅者判定写操作用（A4-01 §4）
            "target": run.action.target,  # actor = 连接器 id
        },
    )
