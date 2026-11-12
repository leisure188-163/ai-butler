"""Run 模型（A2-01 §3）：一次 Action 的执行记录 + 结果 / 证据 / 修复提示。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from kabao_core.domain.action import Action
from kabao_core.domain.errors import DomainError
from kabao_core.domain.results import ResultKind, Status


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_BUDGET = timedelta(seconds=30)  # 时间预算默认值；触发器/端可覆盖


class RunAlreadyFinished(DomainError):
    pass


class BudgetExceeded(DomainError):
    """时间预算耗尽：停止等待并如实上报，不静默截断（A2-01 §3）。"""

    def __init__(self, budget: timedelta) -> None:
        self.budget = budget
        super().__init__(
            f"时间预算 {budget.total_seconds():.3f}s 已超，停止等待并如实上报；"
            "底层调用可能仍在后台执行至自然结束（不静默截断），重复领取由幂等键兜底"
        )


@dataclass(frozen=True)
class Evidence:
    """结构化证据：原始错误码 / 响应摘要，折叠展示用（A2-01 §3）。

    脱敏责任在适配器；凭据明文绝不入内（A4-01 §1）。
    """

    summary: str  # 响应摘要（脱敏后）
    raw_code: str | None = None  # 原始业务码（协议变更探测的数据来源，ADR-002）


@dataclass(frozen=True)
class RepairHint:
    """人话原因 + 修复动作 id：支撑"待处理 → 一键修复"（A2-01 §2）。"""

    reason: str
    action_id: str


@dataclass(frozen=True)
class RunResult:
    """Run 的结果：Status + 谓词 + 证据 + 修复提示。"""

    status: Status
    evidence: tuple[Evidence, ...] = ()
    repair_hint: RepairHint | None = None

    @property
    def kind(self) -> ResultKind:
        return self.status.kind


@dataclass
class Run:
    """一次 Action 的执行记录（A2-01 §3）。终态经 finish 落定，不可回退。"""

    id: str
    action: Action
    account_id: str  # 所有 Run / Event / Sample 都挂 account_id（A2-01 §1）
    idempotency_key: str  # 空串 = 只读动作，无幂等语义
    started_at: datetime = field(default_factory=now_utc)
    budget: timedelta = DEFAULT_BUDGET  # 时间预算是一等属性（A2-01 §3）
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
