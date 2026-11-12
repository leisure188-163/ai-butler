"""用例层：跨端编排唯一入口（R6）。

- ExecuteAction：幂等键 / 时间预算 / dry_run 硬承诺 / 协议变更探测（A2-01 §3）。
  触发器只负责"发起 Run"，所有业务判断都在这里（A2-01 §4）。
- ScanCredentialExpiry / AssessAccountHealth：L0 底座（A4-01 §1~2）。
- ListPending：待处理聚合（A3-01「今天」页），谓词在 core（端零映射）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping

from kabao_core.application.ports import (
    AccountRepository,
    EventSink,
    HealthStateStore,
    PortSelector,
    ProvisionPort,
    ProvisionRequest,
    RunLedger,
    UsagePort,
    UsageRequest,
    UsageStore,
    VaultPort,
    new_id,
)
from kabao_core.domain.account import Account, main_account_id
from kabao_core.domain.action import Action, ActionKind
from kabao_core.domain.errors import DomainError
from kabao_core.domain.event import Event, EventType, Severity, run_finished_event
from kabao_core.domain.health import (
    RISK_NO_AUTH_STREAK,
    AccountHealth,
    HealthLevel,
    credential_level,
    worst_level,
)
from kabao_core.domain.results import Status, UnknownEngineCode
from kabao_core.domain.run import (
    DEFAULT_BUDGET,
    BudgetExceeded,
    Evidence,
    Run,
    RunResult,
    now_utc,
)
from kabao_core.domain.usage import (
    QUOTA_LOW_RATIO,
    UsageSnapshot,
    is_quota_low,
    quota_ratio,
)
from kabao_core.domain.vault import EXPIRING_WINDOW_DAYS


# --- Kabao：动作执行（A2-01 §3 编排语义）---

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
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kabao-run")
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


# --- Kabao：L0 底座用例（A4-01）---

_CRED_EVENT_LEVELS = (
    HealthLevel.EXPIRING,
    HealthLevel.EXPIRED,
)
_ACCOUNT_SEVERITY = {
    HealthLevel.HEALTHY: Severity.SILENT,  # 恢复健康 = 好消息零打扰（A4-01 §2 静默）
    HealthLevel.EXPIRING: Severity.BADGE,
    HealthLevel.EXPIRED: Severity.BADGE,
    HealthLevel.INVALID: Severity.BADGE,
    HealthLevel.RISK: Severity.PUSH,  # 封号风险 push 通知（A4-01 §2）
}


@dataclass
class ScanCredentialExpiry:
    """凭据到期扫描（A4-01 §1 到期监控 job 的核心逻辑）。

    - 比对有效期，负责人产出 CREDENTIAL_EXPIRING / CREDENTIAL_EXPIRED 事件
    - 以"上一次已通知级别"做变更检测：级别不变不重发（防每日 job 刷屏）；
      恢复只清记忆不产事件（A2-01 §5 事件类型无恢复事件，不发明）
    - 分级谓词 credential_level 在 core 重算一遍——不计 adapter 里的
      health() 快照时点，保证单源且时钟可注入（测试确定性）
    """

    vault: VaultPort
    sink: EventSink
    states: HealthStateStore
    clock: Callable[[], datetime] = now_utc
    warn_window_days: int = EXPIRING_WINDOW_DAYS

    def execute(self) -> list[Event]:
        now = self.clock()
        published: list[Event] = []
        for hp in self.vault.health():
            level = credential_level(
                hp.expires_at, now, warn_window_days=self.warn_window_days
            )
            previous = self.states.get_credential_notified_level(hp.account_id, hp.kind)
            if level is HealthLevel.HEALTHY:
                # 只清记忆不产事件（A2-01 §5 无恢复事件类型，不发明）
                self.states.set_credential_notified_level(hp.account_id, hp.kind, level)
                continue
            if previous == level.value:
                continue  # 已通知过，同一级别不重发
            event = Event.new(
                EventType.CREDENTIAL_EXPIRING
                if level is HealthLevel.EXPIRING
                else EventType.CREDENTIAL_EXPIRED,
                severity=Severity.BADGE,  # 预警=徽标，不 push（A4-01 §2）
                account_id=hp.account_id,
                payload={
                    "kind": hp.kind,
                    "expires_at": "" if hp.expires_at is None else hp.expires_at.isoformat(),
                    "window_days": str(self.warn_window_days),
                },
            )
            self.sink.publish(event)
            self.states.set_credential_notified_level(hp.account_id, hp.kind, level)
            published.append(event)
        return published


@dataclass
class AssessAccountHealth:
    """账号健康评定（A4-01 §2）：凭据有效期 + 台账 NO_AUTH 连败 → 五级。

    输入合成规则（core 单源，端零映射）：
    - 连败 = 台账最近 Run 从新往旧数，NO_AUTH 连续个数（只看 risk_streak 上限条）
    - 连败 >= risk_streak → risk（覆盖 invalid/expired——恢复无从谈起，风险最优先）
    - 无连败但有凭据 expired → expired；最近一次 Run 是 NO_AUTH → invalid
    - 无上述事实但有凭据 expiring → expiring；否则 healthy
    - 已知级别的变更才发 ACCOUNT_HEALTH_CHANGED（severity 按 _ACCOUNT_SEVERITY）；
      首评即 healthy 不发（无事发生），首评即异常发（新事实要进"待处理"）
    - recovery 到 healthy 发 SILENT 事件（保持 UI 同步，但零打扰）
    """

    vault: VaultPort
    ledger: RunLedger
    sink: EventSink
    states: HealthStateStore
    clock: Callable[[], datetime] = now_utc
    risk_streak: int = RISK_NO_AUTH_STREAK

    def execute(self, account_id: str) -> AccountHealth:
        now = self.clock()
        streak = 0
        for run in self.ledger.list_for_account(account_id, limit=self.risk_streak):
            if run.result is None or run.result.status is not Status.NO_AUTH:
                break
            streak += 1

        ev: list[str] = []
        cred = HealthLevel.HEALTHY
        for hp in self.vault.health():
            if hp.account_id != account_id:
                continue
            lvl = credential_level(
                hp.expires_at, now, warn_window_days=EXPIRING_WINDOW_DAYS
            )
            if lvl is not HealthLevel.HEALTHY:
                when = "" if hp.expires_at is None else f"（{hp.expires_at:%Y-%m-%d %H:%M} 到期）"
                ev.append(f"凭据 {hp.kind} {lvl.value}{when}")
            cred = worst_level(cred, lvl)

        if streak >= self.risk_streak:
            level = HealthLevel.RISK
            ev.append(f"连续 {streak} 次鉴权失败（NO_AUTH）")
        elif cred is HealthLevel.EXPIRED:
            level = HealthLevel.EXPIRED
        elif streak >= 1:
            level = HealthLevel.INVALID
        elif cred is HealthLevel.EXPIRING:
            level = HealthLevel.EXPIRING
        else:
            level = HealthLevel.HEALTHY

        previous = self.states.get_account_level(account_id)
        self.states.set_account_level(account_id, level)
        should_publish = (
            (previous != level)
            if previous is not None
            else (level is not HealthLevel.HEALTHY)
        )
        # 首评即 healthy = 无事发生，不打扰；首评即异常 = 新事实要进待处理；
        # 已知级别的变更（含恢复 healthy）= 发事件，恢复时 severity=SILENT
        if should_publish:
            self.sink.publish(
                Event.new(
                    EventType.ACCOUNT_HEALTH_CHANGED,
                    severity=_ACCOUNT_SEVERITY[level],
                    account_id=account_id,
                    payload={"level": level.value},
                )
            )
        return AccountHealth.build(
            account_id=account_id, level=level, evidence=tuple(ev), checked_at=now
        )


@dataclass
class RegisterAccount:
    """账号停靠（A2-01 §1）：Provider 下注册名册位，幂等（重复停同一位返回既有账号）。

    凭据不在这里——Connector 的接入流程（dock）仅负责身份落册，凭据经
    它自己的解锁协议直接进 vault（kinds 由 manifest 申报，最小授权 A2-02 §5）。
    """

    accounts: AccountRepository

    def execute(
        self, provider: str, display_name: str, *, account_id: str | None = None
    ) -> Account:
        aid = account_id or main_account_id(provider)
        existing = self.accounts.get(aid)
        if existing is not None:
            return existing  # 幂等：同Provider名册位已存在，不重复建
        account = Account(
            id=aid, provider=provider.strip(), display_name=display_name,
            created_at=now_utc(),
        )
        self.accounts.save(account)
        return account


@dataclass
class ListPending:
    """待处理聚合（A3-01「今天」页）：is_attention 结果的 Run，新→旧。

    "什么算待处理" = core 谓词（result.kind.is_attention）——端只消费，
    不做 if status in [...] 式映射（红线 2）。attention 的文案/证据/repair_hint
    均由 RunResult 自带，端原样渲染。
    """

    ledger: RunLedger
    limit: int = 50

    def execute(self, *, scan_limit: int = 200) -> list[Run]:
        pending = [
            run
            for run in self.ledger.list_recent(limit=scan_limit)
            if run.result is not None and run.result.kind.is_attention
        ]
        return pending[:self.limit]


# --- Kabao：R2 用量采集（块①设计）---


@dataclass(frozen=True)
class CollectOutcome:
    """一次采集的如实报告：落了什么、漏了什么（单家失败不拖累编排，不静默）。"""

    account_id: str
    target: str
    snapshot_saved: bool = False
    aggregate_saved: bool = False
    ledger_saved: int = 0  # record_id 幂等去重后的新增流水条数
    quota_low: tuple[str, ...] = ()  # 本次触发 QUOTA_LOW 事件的包名
    error: str | None = None


@dataclass
class CollectUsage:
    """用量采集编排（R2：dock 顺带 + 每日调度共用的核心逻辑）。

    - 端口按 target 精确选路（同 ADR-003 路由纪律）；未接入如实报 outcome.error
    - 三段可空各存各的：快照 / 聚合 / 流水（record_id 幂等去重）
    - QUOTA_LOW 变更才产事件：与上一帧同包占比比较——首评异常也发，仍低不重发，
      恢复不产事件（A2-01 §5 无恢复事件类型），再跌回再发；记忆 = 快照历史本身
    - 端口异常收进 outcome.error（dock 顺带采集绝不打断停靠编排），不静默
    """

    ports: Mapping[str, UsagePort]
    store: UsageStore
    sink: EventSink
    clock: Callable[[], datetime] = now_utc
    budget: timedelta = DEFAULT_BUDGET
    threshold: float = QUOTA_LOW_RATIO

    def execute(self, target: str, account_id: str) -> CollectOutcome:
        port = self.ports.get(target)
        if port is None:
            return CollectOutcome(
                account_id=account_id,
                target=target,
                error=f"连接器 {target!r} 未接入用量采集通道",
            )
        try:
            result = port.collect(
                UsageRequest(
                    target=target, account_id=account_id, deadline=self.clock() + self.budget
                )
            )
        except Exception as e:  # noqa: BLE001 —— 采集失败如实进 outcome，不打断编排
            return CollectOutcome(
                account_id=account_id,
                target=target,
                error=f"用量采集失败: {type(e).__name__}: {e}",
            )

        snapshot_saved = aggregate_saved = False
        ledger_saved = 0
        low_names: list[str] = []
        latest = self.store.list_snapshots(account_id, limit=1)
        previous = latest[0] if latest else None
        if result.snapshot is not None:
            self.store.save_snapshot(result.snapshot)
            snapshot_saved = True
            low_names = self._quota_low_events(account_id, previous, result.snapshot)
        if result.aggregate is not None:
            self.store.save_aggregate(result.aggregate)
            aggregate_saved = True
        if result.ledger:
            ledger_saved = self.store.append_ledger(result.ledger)
        return CollectOutcome(
            account_id=account_id,
            target=target,
            snapshot_saved=snapshot_saved,
            aggregate_saved=aggregate_saved,
            ledger_saved=ledger_saved,
            quota_low=tuple(low_names),
        )

    # --- 内部 ---

    def _quota_low_events(
        self,
        account_id: str,
        previous: UsageSnapshot | None,
        current: UsageSnapshot,
    ) -> list[str]:
        """QUOTA_LOW 变更检测（记忆 = 上一帧快照）：新低才发，仍低不重发。"""
        prev_ratio = (
            {p.package_id: quota_ratio(p) for p in previous.packages}
            if previous is not None
            else {}
        )
        names: list[str] = []
        for pkg in current.packages:
            if not is_quota_low(pkg, threshold=self.threshold):
                continue
            prev = prev_ratio.get(pkg.package_id)
            if prev is not None and prev <= self.threshold:
                continue  # 仍然低：变更检测不重发（防每日采集刷屏）
            ratio = quota_ratio(pkg)
            self.sink.publish(
                Event.new(
                    EventType.QUOTA_LOW,
                    severity=Severity.BADGE,  # 预警 = 徽标不 push（A4-01 §2 同纪律）
                    account_id=account_id,
                    payload={
                        "package_id": pkg.package_id,
                        "name": pkg.name,
                        "remaining": str(pkg.remaining),
                        "total": str(pkg.total),
                        "unit": pkg.unit,
                        "ratio": f"{ratio:.2f}" if ratio is not None else "",
                    },
                )
            )
            names.append(pkg.name)
        return names
