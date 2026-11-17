"""豆包 RunResult 小工厂（从 adapter.py 拆出控制行数）。

只做 status/evidence/repair_hint 的形状拼装，不含 CDP 控制流。
"""

from __future__ import annotations

from butler_core.execution.domain import Evidence, RepairHint, RunResult
from butler_core.shared.results import Status


def daily_checkin(payload: dict) -> dict | None:
    """detail 判定字段路径（PROTOCOL §2）：data.tasks[campaign_code=daily_signin]。"""
    for task in (payload.get("data") or {}).get("tasks") or []:
        if task.get("campaign_code") == "daily_signin":
            return task.get("daily_checkin") or {}
    return None


def failed(summary: str, *, raw_code: str | None = None) -> RunResult:
    return RunResult(Status.FAILED, evidence=(Evidence(summary, raw_code=raw_code),))


def pending(
    summary: str,
    *,
    hint: str = "豆包客户端未带调试端口运行（暂态，不算失败）",
    action: str = "dock",
) -> RunResult:
    """PENDING 显式分语境（2026-11-17 bug 修复）：端口不可达与身份不符是两种
    修复动作，提示语必须跟着语境走，不许复用端口语境误导用户。"""
    return RunResult(
        Status.PENDING,
        evidence=(Evidence(summary),),
        repair_hint=RepairHint(hint, action),
    )
