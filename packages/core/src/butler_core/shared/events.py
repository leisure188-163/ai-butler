"""事件模型（shared 内核，A2-01 §5）：L0 通知中心的唯一输入。

依赖恒等式：shared 不 import 任何业务域——run_finished_event 对 Run 采用
结构化协议（duck typing），避免反向依赖 execution 域。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping, Protocol
from uuid import uuid4

from butler_core.shared.errors import DomainError
from butler_core.shared.time import now_utc


class Severity(StrEnum):
    """打扰级别（A4-01 §3）：用户可在设置里按事件类型覆盖。"""

    SILENT = "silent"
    BADGE = "badge"
    PUSH = "push"


class EventType(StrEnum):
    """事件类型全集（A2-01 §5），六型不许增改。"""

    RUN_FINISHED = "RUN_FINISHED"
    CREDENTIAL_EXPIRING = "CREDENTIAL_EXPIRING"
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED"
    QUOTA_LOW = "QUOTA_LOW"
    PROTOCOL_CHANGED = "PROTOCOL_CHANGED"
    ACCOUNT_HEALTH_CHANGED = "ACCOUNT_HEALTH_CHANGED"


@dataclass(frozen=True)
class Event:
    """事件 schema：{id, type, ts, account_id?, severity, payload}。"""

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


class EventSink(ABC):
    """事件总线端口（shared）：所有域只发布，不关心订阅者。"""

    @abstractmethod
    def publish(self, event: Event) -> None: ...


class _FinishedRun(Protocol):
    """run_finished_event 所需的最小结构——避免 shared → execution 反向依赖。"""

    id: str
    account_id: str

    @property
    def result(self) -> object | None: ...

    @property
    def action(self) -> object: ...


def run_finished_event(run: _FinishedRun) -> Event:
    """RUN_FINISHED 工厂：severity 由 core 谓词推导（端零映射，红线 2）。

    全部成功 = silent；只有 is_attention 结果才产生可见通知。
    """

    result = run.result
    if result is None:
        raise DomainError(f"Run {run.id} 未到终态，无 RUN_FINISHED 事件")
    kind = result.kind  # type: ignore[attr-defined]
    status = result.status  # type: ignore[attr-defined]
    severity = Severity.BADGE if kind.is_attention else Severity.SILENT
    return Event.new(
        EventType.RUN_FINISHED,
        severity=severity,
        account_id=run.account_id,
        payload={
            "run_id": run.id,
            "status": status.value,
            "action": run.action.kind.value,  # type: ignore[attr-defined]
            "target": run.action.target,  # type: ignore[attr-defined]
        },
    )
