"""待办聚合用例（A2-08 §4）：每 (kind, target, account) 只看最新 Run 的结果。

"什么算待处理" = core 谓词（端零映射，红线 2）。新旧按 Run 时间取最新一条：
最新是 attention → 进待办；最新已恢复/已失败（非 attention）→ 旧的历史失败
不再呈现，避免"修好了旧条目还挂在待办里"（ADR-015 可修闭环）。
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.execution.domain import Run
from butler_core.execution.ports import RunLedger


@dataclass
class ListPending:
    ledger: RunLedger
    limit: int = 50

    def execute(self, *, scan_limit: int = 200) -> list[Run]:
        seen: set[tuple[str, str, str]] = set()
        pending: list[Run] = []
        for run in self.ledger.list_recent(limit=scan_limit):
            if run.result is None:
                continue
            key = (run.action.kind.value, run.action.target, run.account_id)
            if key in seen:
                continue
            seen.add(key)  # 先占位：同键更旧的 Run 一律让位给最新结果
            if run.result.kind.is_attention:
                pending.append(run)
        return pending[: self.limit]
