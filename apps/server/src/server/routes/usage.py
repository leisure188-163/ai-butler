"""用量雷达域 API（R2 三实体投影：快照 / 聚合原话 / 流水，可得性如实分列）。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from butler_core.usage.domain import is_quota_low

router = APIRouter(tags=["butler"])


class PackageQuotaOut(BaseModel):
    package_id: str
    name: str
    total: float
    used: float
    remaining: float
    unit: str
    cycle_end: datetime | None
    status: str


class ForecastOut(BaseModel):
    """耗尽预测（core forecast_exhaustion 出产）：不足两帧 = 空列表 → UI「采集中」。"""

    package_id: str
    name: str
    unit: str
    remaining: float
    per_day: float
    days_left: float | None
    exhausted_on: date | None


class LedgerEntryOut(BaseModel):
    record_id: str
    amount: float
    unit: str
    kind: str
    occurred_at: datetime | None


class RadarAccountOut(BaseModel):
    """单账号雷达行：无快照 = packages 空（尚未采集）；doubao 只有流水。"""

    account_id: str
    provider: str
    display_name: str
    collected_at: datetime | None
    packages: list[PackageQuotaOut]
    forecasts: list[ForecastOut]
    quota_low: list[str]  # core is_quota_low 现算的当前低额包 id（投影非决策）
    aggregate_summary: dict[str, Any] | None  # 服务端聚合原话（不派生，端零映射）
    aggregate_collected_at: datetime | None
    recent_ledger: list[LedgerEntryOut]


class CollectOutcomeOut(BaseModel):
    account_id: str
    target: str
    snapshot_saved: bool
    aggregate_saved: bool
    ledger_saved: int
    quota_low: list[str]
    error: str | None


@router.post("/usage/collect", response_model=list[CollectOutcomeOut])
def collect_usage(request: Request) -> list[CollectOutcomeOut]:
    """全账号用量采集（手动触发）：逐账号 CollectUsage，单账号失败不拖累其余。"""
    kit = request.app.state.kit
    outcomes = [
        kit.collect_usage.execute(account.provider, account.id)
        for account in kit.accounts.list_all()
    ]
    return [
        CollectOutcomeOut(
            account_id=o.account_id,
            target=o.target,
            snapshot_saved=o.snapshot_saved,
            aggregate_saved=o.aggregate_saved,
            ledger_saved=o.ledger_saved,
            quota_low=list(o.quota_low),
            error=o.error,
        )
        for o in outcomes
    ]


@router.get("/usage/radar", response_model=list[RadarAccountOut])
def usage_radar(request: Request) -> list[RadarAccountOut]:
    """额度雷达：最新快照 + 相邻差分预测 + 聚合原话 + 最近流水（每账号一行）。"""
    from butler_core.usage.domain import forecast_exhaustion

    kit = request.app.state.kit
    out: list[RadarAccountOut] = []
    for account in kit.accounts.list_all():
        snapshots = kit.usage_store.list_snapshots(account.id, limit=2)
        current = snapshots[0] if snapshots else None
        previous = snapshots[1] if len(snapshots) > 1 else None
        forecasts = forecast_exhaustion(previous, current) if current else ()
        aggregate = kit.usage_store.latest_aggregate(account.id)
        out.append(
            RadarAccountOut(
                account_id=account.id,
                provider=account.provider,
                display_name=account.display_name,
                collected_at=current.collected_at if current else None,
                packages=[
                    PackageQuotaOut(
                        package_id=p.package_id,
                        name=p.name,
                        total=p.total,
                        used=p.used,
                        remaining=p.remaining,
                        unit=p.unit,
                        cycle_end=p.cycle_end,
                        status=p.status,
                    )
                    for p in (current.packages if current else ())
                ],
                forecasts=[
                    ForecastOut(
                        package_id=f.package_id,
                        name=f.name,
                        unit=f.unit,
                        remaining=f.remaining,
                        per_day=f.per_day,
                        days_left=f.days_left,
                        exhausted_on=f.exhausted_on,
                    )
                    for f in forecasts
                ],
                quota_low=[
                    p.package_id
                    for p in (current.packages if current else ())
                    if is_quota_low(p)
                ],
                aggregate_summary=dict(aggregate.summary) if aggregate else None,
                aggregate_collected_at=aggregate.collected_at if aggregate else None,
                recent_ledger=[
                    LedgerEntryOut(
                        record_id=e.record_id,
                        amount=e.amount,
                        unit=e.unit,
                        kind=e.kind,
                        occurred_at=e.occurred_at,
                    )
                    for e in kit.usage_store.list_ledger(account.id, limit=10)
                ],
            )
        )
    return out
