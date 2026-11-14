"""动作执行用例（A2-01 §3 编排语义）：幂等键 / 时间预算 / dry_run 硬承诺 / 协议变更探测。

触发器只负责"发起 Run"，所有业务判断都在这里（A2-01 §4）。
（自 application/usecases.py 按用例边界分出——conventions/4 §2.3，2026-11-14。）
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import timedelta

from butler_core.execution.ports import (
    PortSelector,
    ProvisionPort,
    ProvisionRequest,
    RunLedger,
)
from butler_core.shared.events import EventSink
from butler_core.shared.ids import new_id
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.errors import DomainError
from butler_core.shared.events import Event, EventType, Severity, run_finished_event
from butler_core.shared.results import Status, UnknownEngineCode
from butler_core.execution.domain import (
    DEFAULT_BUDGET,
    BudgetExceeded,
    Evidence,
    Run,
    RunResult,
)


# --- Butler：动作执行（A2-01 §3 编排语义）---

class UnsupportedAction(DomainError):
    """动作类型没有接入端口——用例层显式拒绝，绝不静默。"""


class InvalidRequest(DomainError):
    """请求形状非法（窗口缺失 / 预算非法 / dry_run 用错地方）。"""


class DryRunNotSupported(DomainError):
    """Connector 未申报 dry_run 能力——硬承诺：拒绝执行，绝不静默降级成真实执行。"""

    def __init__(self, target: str) -> None:
        super().__init__(
            f"连接器 {target!r} 未申报 dry_run 能力，已拒绝执行（不静默降级）"
        )


@dataclass(frozen=True)
class RunRequest:
    """用例入参（AO，R7）：Run 的形状由 core 定，端与触发器只填这里。"""

    action: Action
    account_id: str
    budget: timedelta = DEFAULT_BUDGET  # 时间预算是 Run 的一等属性（A2-01 §3）
    window: str = ""  # 领取窗口（如 "2026-11-10"）；provision 类动作必填
    dry_run: bool = False  # 仅 provision.run 有意义

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise InvalidRequest("account_id 不能为空")
        if self.budget <= timedelta(0):
            raise InvalidRequest("时间预算必须为正")


def idempotency_key(action: Action, account_id: str, window: str) -> str:
    """幂等键 = (kind, account_id, 窗口)——重复触发不会重复领取（A2-01 §3）。"""
    return f"{action.kind.value}:{account_id}:{window}"


@dataclass
class ExecuteAction:
    """发起并落实一次 Action → Run。

    ports 是**选择器**（ADR-003）：M1 起多连接器共用一个 kind，用例按
    action.target 精确挑连接器端口（core 通用规则，不写任何产品分支）。
    """

    ledger: RunLedger
    sink: EventSink
    ports: PortSelector

    def execute(self, request: RunRequest) -> Run:
        action = request.action

        # 请求形状校验先行——与端口是否接入无关（A2-01 §3）
        if request.dry_run and action.kind is not ActionKind.PROVISION_RUN:
            raise InvalidRequest("dry_run 仅对 provision.run 有意义")
        if action.kind.is_idempotent_write and not request.window.strip():
            raise InvalidRequest(
                "provision 动作必须提供领取窗口——幂等键 = (kind, account_id, 窗口)"
            )

        port = self.ports(action) if callable(self.ports) else self.ports[action.kind]
        if port is None:
            raise UnsupportedAction(
                f"动作 {action.kind.value} 目标 {action.target!r} 未接入端口，"
                "用例层拒绝（不静默）"
            )

        # 只读动作无幂等语义（A2-01 §3 幂等键只约束领取类写动作）
        key = (
            idempotency_key(action, request.account_id, request.window)
            if action.kind.is_idempotent_write
            else ""
        )
        if key:
            previous = self.ledger.find_by_idempotency_key(key)
            if (
                previous is not None
                and previous.result is not None
                and previous.result.kind.is_pass
            ):
                return previous  # 幂等命中：回放原 Run，绝不重复发起

        if request.dry_run and not port.capabilities().dry_run:
            # 硬承诺（A2-01 §3）：Connector 不支持 dry_run → 用例层拒绝，
            # 绝不静默降级成真实执行（旧系统事故教训，红线 5）。
            raise DryRunNotSupported(action.target)

        run = Run(
            id=new_id(),
            action=action,
            account_id=request.account_id,
            idempotency_key=key,
            budget=request.budget,
        )
        self.ledger.save(run)

        req = ProvisionRequest(
            kind=action.kind,
            target=action.target,
            account_id=request.account_id,
            params=dict(action.params),  # 拷贝：防适配器改动 Action 内部
            deadline=run.started_at + request.budget,
            dry_run=request.dry_run,
        )
        try:
            result = self._invoke(port, req, request.budget)
        except UnknownEngineCode as e:
            # 未知业务码 = 上游协议可能已变更（ADR-002）：
            # FAILED + evidence 保留原始码 + PROTOCOL_CHANGED 探测事件。
            self._terminate(
                run,
                RunResult(
                    status=Status.FAILED,
                    evidence=(
                        Evidence(summary="上游返回未注册业务码，协议可能已变更", raw_code=e.code),
                    ),
                ),
                protocol_event=Event.new(
                    EventType.PROTOCOL_CHANGED,
                    severity=Severity.BADGE,
                    account_id=run.account_id,
                    payload={"run_id": run.id, "raw_code": e.code, "dialect": e.dialect},
                ),
            )
            return run
        except BudgetExceeded as e:
            self._terminate(
                run,
                RunResult(status=Status.FAILED, evidence=(Evidence(summary=str(e)),)),
            )
            return run
        except Exception as e:
            # 适配器意外异常：落账 FAILED（台账必有记录）后原样上抛——不吞（红线 5）。
            self._terminate(
                run,
                RunResult(
                    status=Status.FAILED,
                    evidence=(Evidence(summary=f"适配器异常: {type(e).__name__}: {e}"),),
                ),
            )
            raise
        self._terminate(run, result)
        return run

    # --- 内部 ---

    def _invoke(
        self, port: ProvisionPort, req: ProvisionRequest, budget: timedelta
    ) -> RunResult:
        """端口调用 + 时间预算硬约束：超预算立即停止等待并如实上报（A2-01 §3）。

        不静默截断：被放弃的底层调用可能仍在后台执行至自然结束，
        该事实随 evidence 上报；重复领取由幂等键兜底。
        """
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="butler-run")
        try:
            future = pool.submit(port.run, req)
            try:
                return future.result(timeout=budget.total_seconds())
            except FutureTimeout:
                raise BudgetExceeded(budget) from None
        finally:
            pool.shutdown(wait=False)

    def _terminate(
        self, run: Run, result: RunResult, *, protocol_event: Event | None = None
    ) -> None:
        run.finish(result)
        self.ledger.save(run)
        self.sink.publish(run_finished_event(run))  # 通知/台账/统计的统一入口
        if protocol_event is not None:
            self.sink.publish(protocol_event)
