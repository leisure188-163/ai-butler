"""用量采集用例（R2 块①设计）：dock 顺带采集与每日调度共用的核心逻辑。

三段可空各存各的（快照/聚合/流水，record_id 幂等去重）；
QUOTA_LOW 变更检测（记忆 = 上一帧快照），单家失败不拖累编排（不静默）。
（自 application/usecases.py 按用例边界分出——conventions/4 §2.3，2026-11-14。）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Mapping

from butler_core.shared.events import EventSink
from butler_core.usage.ports import UsagePort, UsageRequest, UsageStore
from butler_core.shared.events import Event, EventType, Severity
from butler_core.execution.domain import DEFAULT_BUDGET, now_utc
from butler_core.usage.domain import (
    QUOTA_LOW_RATIO,
    UsageSnapshot,
    is_quota_low,
    quota_ratio,
)


# --- Butler：R2 用量采集（块①设计）---


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

    - 端口按 target 精确选路（同 ADR-005 路由纪律）；未接入如实报 outcome.error
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
