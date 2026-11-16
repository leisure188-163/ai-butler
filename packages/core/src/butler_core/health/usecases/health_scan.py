"""L0 底座健康用例（A4-01 §1~2）：凭据到期扫描 + 账号健康评定。

分级谓词在 core 单源重算，时钟可注入（测试确定性）；
事件 severity 按 A4-01 §2 分级（预警=徽标不 push，风险=push）。
（自 application/usecases.py 按用例边界分出——conventions/4 §2.3，2026-11-14。）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from butler_core.accounts.ports import VaultPort
from butler_core.execution.ports import RunLedger
from butler_core.health.ports import HealthStateStore
from butler_core.shared.errors import DomainError
from butler_core.shared.events import EventSink
from butler_core.shared.events import Event, EventType, Severity
from butler_core.health.domain import (
    RISK_NO_AUTH_STREAK,
    AccountHealth,
    HealthLevel,
    credential_level,
    worst_level,
)
from butler_core.shared.results import Status
from butler_core.execution.domain import now_utc
from butler_core.accounts.domain import EXPIRING_WINDOW_DAYS


# --- Butler：L0 底座用例（A4-01）---

_CRED_EVENT_LEVELS = (
    HealthLevel.EXPIRING,
    HealthLevel.EXPIRED,
)
_ACCOUNT_SEVERITY = {
    HealthLevel.HEALTHY: Severity.SILENT,  # 恢复健康 = 好消息零打扰（A4-01 §2 静默）
    HealthLevel.EXPIRING: Severity.BADGE,
    # 硬失效/凭据被拒是阻塞性事实（领不了、用不了），升级 push：
    # 用户不打开界面也必须知道（ADR-015；A4-01 §2 分级同步收编）
    HealthLevel.EXPIRED: Severity.PUSH,
    HealthLevel.INVALID: Severity.PUSH,
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
            if hp.revoked_at is not None:
                continue  # 已撤销副本不再报到/到期事件（ADR-016）
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
    - 有 NO_AUTH 连败或凭据 expired → 自动撤销本地凭据副本（ADR-016）；
      只清 butler 库，不触碰客户端会话
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
            if hp.revoked_at is not None:
                when = f"（{hp.revoked_at:%Y-%m-%d %H:%M} 撤销）"
                ev.append(f"凭据 {hp.kind} 本地副本已撤销{when}")
                continue  # 已撤销副本不再参与有效期分级（ADR-016）
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

        # 失效即撤销本地副本（ADR-016）：只清 butler 存的凭据，不碰客户端会话；
        # 幂等，重复评估不会重复撤销。触发条件 = 有 NO_AUTH 连败（含由此判出的
        # invalid/risk）或凭据已过期；risk 若来自其它信号则不自动撤销。
        # 撤销失败不掩盖健康结论，只加证据。
        if streak >= 1 or cred is HealthLevel.EXPIRED:
            try:
                revoked = self.vault.revoke(
                    account_id,
                    reason=f"健康级别 {level.value}：自动撤销 butler 本地凭据副本",
                )
            except DomainError as exc:
                ev.append(f"自动撤销本地凭据副本失败：{exc}")
            else:
                if revoked:
                    ev.append(
                        f"已自动撤销 butler 本地凭据副本 {revoked} 项——"
                        "客户端登录态不受影响，重新登录后停靠即可恢复"
                    )
        return AccountHealth.build(
            account_id=account_id, level=level, evidence=tuple(ev), checked_at=now
        )
