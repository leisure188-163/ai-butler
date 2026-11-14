"""执行域（A2-05）：Action / Run / 结果 / 幂等键 / 时间预算。

依赖恒等式：只 import shared；Status 由 shared.results 单源，这里再导出是为了
让旧调用形态 `from butler_core.execution.domain import Status` 仍成立。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Mapping

from butler_core.shared.errors import DomainError
from butler_core.shared.results import ResultKind, Status
from butler_core.shared.time import now_utc

__all__ = [
    "Action",
    "ActionInvalid",
    "ActionKind",
    "BudgetExceeded",
    "DEFAULT_BUDGET",
    "Evidence",
    "RepairHint",
    "Run",
    "RunAlreadyFinished",
    "RunResult",
    "ResultKind",
    "Status",
    "idempotency_key",
    "now_utc",
]

DEFAULT_BUDGET = timedelta(seconds=30)


class ActionKind(StrEnum):
    """动作类型全集（A2-01 §4），八值不许随意扩展。"""

    PROVISION_RUN = "provision.run"
    PROVISION_CLAIM = "provision.claim"
    USAGE_COLLECT = "usage.collect"
    USAGE_QUERY = "usage.query"
    SESSION_EXPORT = "session.export"
    SESSION_IMPORT = "session.import"
    HEALTH_CHECK = "health.check"
    GATEWAY_ROUTE = "gateway.route"

    @property
    def is_idempotent_write(self) -> bool:
        return self in _IDEMPOTENT_KINDS


_IDEMPOTENT_KINDS = frozenset({ActionKind.PROVISION_RUN, ActionKind.PROVISION_CLAIM})


class ActionInvalid(DomainError):
    pass


@dataclass(frozen=True)
class Action:
    """Action = (kind, target, params)；target = 应用 + 账号编址（ADR-008 §2）。"""

    kind: ActionKind
    target: str
    params: Mapping[str, str] = field(default_factory=dict)
    account_key: str = "main"

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise ActionInvalid("target（connector id）不能为空")


class RunAlreadyFinished(DomainError):
    pass


class BudgetExceeded(DomainError):
    """时间预算耗尽：停止等待并如实上报，不静默截断（A2-05 §2）。"""

    def __init__(self, budget: timedelta) -> None:
        self.budget = budget
        super().__init__(
            f"时间预算 {budget.total_seconds():.3f}s 已超，停止等待并如实上报；"
            "底层调用可能仍在后台执行至自然结束（不静默截断），重复领取由幂等键兜底"
        )


@dataclass(frozen=True)
class Evidence:
    summary: str
    raw_code: str | None = None


@dataclass(frozen=True)
class RepairHint:
    reason: str
    action_id: str


@dataclass(frozen=True)
class RunResult:
    status: Status
    evidence: tuple[Evidence, ...] = ()
    repair_hint: RepairHint | None = None

    @property
    def kind(self) -> ResultKind:
        return self.status.kind


@dataclass
class Run:
    """一次 Action 的执行记录；终态经 finish 落定，不可回退。"""

    id: str
    action: Action
    account_id: str
    idempotency_key: str
    started_at: datetime = field(default_factory=now_utc)
    budget: timedelta = DEFAULT_BUDGET
    finished_at: datetime | None = None
    result: RunResult | None = None

    @property
    def is_terminal(self) -> bool:
        return self.result is not None

    def finish(self, result: RunResult, at: datetime | None = None) -> None:
        if self.is_terminal:
            raise RunAlreadyFinished(f"Run {self.id} 已终态，不可回退")
        self.result = result
        self.finished_at = at if at is not None else now_utc()


def idempotency_key(action: Action, account_id: str, window: str) -> str:
    """幂等键 = (kind, account_id, 窗口)——按账号粒度（ADR-008 §4）。"""

    return f"{action.kind.value}:{account_id}:{window}"
