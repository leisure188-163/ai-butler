"""停靠触发器（A2-01 §4 Trigger=cron）：高密度触发 × 幂等领取 = 兜底单点失败。

教训继承（A0-01 §12 依据一）：触发时刻机器可能关机/断网/刚开机网络未就绪，
不过多给触发机会；领取侧幂等（幂等键 = kind+account+窗口）自然挡重复。
业务判断不在触发器——窗口归属走 core 的 claim_window，重复领取由
ExecuteAction 幂等回放兜底，这里的 fired 集合只是"别在同一刻重复调"的降噪。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from butler_core.accounts.ports import AccountRepository
from butler_core.execution.usecases.execute_action import ExecuteAction, RunRequest
from butler_core.execution.domain import Action, ActionKind
from butler_core.execution.domain import now_utc
from butler_core.scheduling.domain import claim_window
from butler_core.shared.health_level import HealthLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduleEntry:
    """一个连接器的触发声明（来自 manifest.schedule，注册表解码后传入）。"""

    target: str
    times: tuple[str, ...]  # 触发时刻 HH:MM（本机墙钟）
    refresh_at: str  # 领区窗口结算点 HH:MM（core claim_window 依据）
    budget: timedelta

    def __post_init__(self) -> None:
        if not self.times:
            raise ValueError(f"{self.target}: schedule.times 不能为空")
        if self.budget <= timedelta(0):
            raise ValueError(f"{self.target}: 预算必须为正")


@dataclass
class CheckinSchedule:
    """逐分钟 tick：命中触发位 → 对该连接器名册全部账号发起 provision.run。"""

    execute_action: ExecuteAction
    accounts: AccountRepository
    entries: tuple[ScheduleEntry, ...]
    clock: Callable[[], datetime] = now_utc
    grace: timedelta = timedelta(minutes=2)  # tick 间隔抖动容差
    #: 健康闸门（ADR-015）：返回当前健康评定；失效账户不再按班次反复打上游。
    assess_health: Callable[[str], object] | None = None
    _fired: set[tuple[str, str, str, str]] = field(default_factory=set)
    _skipped: set[tuple[str, str, str]] = field(default_factory=set)

    def tick(self) -> list[str]:
        """返回本轮实际落账的 run id（供测试与运维观测）。"""
        now = self.clock()
        self._fired = {k for k in self._fired if k[3] == self._current_window(now)}
        self._skipped = {k for k in self._skipped if k[2] == self._current_window(now)}
        started: list[str] = []
        for entry in self.entries:
            window = claim_window(now, entry.refresh_at)
            for slot in entry.times:
                if not self._due(now, slot):
                    continue
                for account in self.accounts.list_by_provider(entry.target):
                    if self._blocked(account.id):
                        key = (entry.target, account.id, window)
                        if key not in self._skipped:
                            self._skipped.add(key)
                            logger.info(
                                "跳过 %s × %s：登录态失效，等待修复后手动重试",
                                entry.target,
                                account.id,
                            )
                        continue
                    key = (entry.target, account.id, slot, window)
                    if key in self._fired:
                        continue
                    self._fired.add(key)
                    run_id = self._fire(entry, account.id, window)
                    if run_id:
                        started.append(run_id)
                        self._assess(account.id)
        return started

    def _blocked(self, account_id: str) -> bool:
        """健康闸门：invalid/expired/risk 不自动重试（修复后由手动重试恢复）。

        只读健康评定，不改事实；未知形状（无 level）按未失效处理（不误拦）。
        """
        if self.assess_health is None:
            return False
        level = getattr(self.assess_health(account_id), "level", None)
        return level in (
            HealthLevel.INVALID,
            HealthLevel.EXPIRED,
            HealthLevel.RISK,
        )

    def _assess(self, account_id: str) -> None:
        """动作落地后即时评估（登录态失效立刻产健康事件）；失败不打断调度。"""
        if self.assess_health is None:
            return
        try:
            self.assess_health(account_id)
        except Exception:
            logger.exception("触发后健康评估失败（已隔离，本条已落账）")

    # --- 内部 ---

    @staticmethod
    def _current_window(now: datetime) -> str:
        return now.astimezone().date().isoformat()

    def _due(self, now: datetime, slot: str) -> bool:
        hour, minute = int(slot[:2]), int(slot[3:])
        local = now.astimezone()
        moment = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        elapsed = local - moment
        return timedelta(0) <= elapsed < self.grace

    def _fire(self, entry: ScheduleEntry, account_id: str, window: str) -> str | None:
        """触发一次（异常隔离到条目级：一段断,其余照常——红线 5 的非静默是"留账"）。"""
        try:
            run = self.execute_action.execute(
                RunRequest(
                    action=Action(kind=ActionKind.PROVISION_RUN, target=entry.target),
                    account_id=account_id,
                    window=window,
                    budget=entry.budget,
                )
            )
        except Exception:
            # ExecuteAction 自身已在适配器异常路径留账 FAILED，这里只隔离组播；
            # 记录是"不静默"的最低要求。
            logger.exception(
                "触发 %s × %s 落账失败（隔离本条，其余照常）", entry.target, account_id
            )
            return None
        return run.id
