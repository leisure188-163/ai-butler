"""待处理聚合用例（A3-01「今天」页）：is_attention 结果的 Run，新→旧。

"什么算待处理" = core 谓词（端零映射，红线 2）。
（自 application/usecases.py 按用例边界分出——conventions/04 §2.3，2026-11-14。）
"""

from __future__ import annotations

from dataclasses import dataclass

from kabao_core.application.ports import RunLedger
from kabao_core.domain.run import Run


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
