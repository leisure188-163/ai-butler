"""待办聚合用例（A2-08 §4）：is_attention 结果的 Run，新→旧、按账号去重。

"什么算待处理" = core 谓词（端零映射，红线 2）；同一 (kind, account, 窗口)
的待办只呈现一条（A2-08 §2 不变量 3）。
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
        seen: set[str] = set()
        pending: list[Run] = []
        for run in self.ledger.list_recent(limit=scan_limit):
            if run.result is None or not run.result.kind.is_attention:
                continue
            key = run.idempotency_key or (
                f"{run.action.kind.value}:{run.account_id}:{run.id}"
            )
            if key in seen:
                continue
            seen.add(key)
            pending.append(run)
        return pending[: self.limit]
