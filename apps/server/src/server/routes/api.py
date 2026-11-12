"""Kabao 领域 API（M0 三页数据源）：账号 / 领取记录 / 待处理。

序列化纪律（红线 2）：本模块只做 domain 对象 → JSON 的形状投影，
level / status / repair_hint 等**语义字面量由 core 出产并原样传递**；
这里没有 if status in [...]，页面谓词交给 kind 驱动。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from kabao_core.domain.run import Run
from kabao_core.domain.usage import is_quota_low
from kabao_core.domain.vault import CredentialHealth

router = APIRouter(tags=["kabao"])

_MAX_LIMIT = 200


# --- 响应形状（投影，不含语义决策）---


class CredentialOut(BaseModel):
    account_id: str
    kind: str
    level: str  # HealthLevel.value（core 出产字面量）
    signal: str  # HealthLevel.signal（core 出产视觉分类，端零映射）
    expires_at: datetime | None


class AccountOut(BaseModel):
    account_id: str
    provider: str  # 连接器 id（号册归属，A2-01 §1）
    display_name: str  # 应用名（账号册出产）
    level: str  # AssessAccountHealth 出产的五级字面量
    signal: str  # core 出产视觉分类（ok/notice/attention/danger）
    evidence: list[str]
    repair_hint: str | None  # core 出产文案，前端直渲染
    credentials: list[CredentialOut]


class AppOut(BaseModel):
    """应用名册行：连接器能力矩阵 + 调度缺省（A2-02 §2 的端侧投影）。"""

    id: str
    display: str
    capabilities: list[str]  # ActionKind.value 列表（core 词表）
    credential_kinds: list[str]
    schedule_times: list[str]  # HH:MM 触发时间
    account_id: str | None  # {id}:main 卡位（M1 单账户），未导入 = None


class ImportOut(BaseModel):
    target: str
    accounts: list[str]
    issues: list[str]


class RunIn(BaseModel):
    """手动领取入参：target 必填；账号缺省 = 该连接器卡位；窗口缺省 = core 规则。"""

    target: str
    account_id: str | None = None
    dry_run: bool = False


class EvidenceOut(BaseModel):
    summary: str
    raw_code: str | None = None


class RunOut(BaseModel):
    id: str
    kind: str  # ActionKind.value
    target: str
    account_id: str
    started_at: datetime
    finished_at: datetime | None
    status: str | None  # Status.value（oracle 方言字面量，端零映射）
    signal: str  # ResultKind.signal（core 出产视觉分类）
    evidence: list[EvidenceOut]
    repair_reason: str | None
    repair_action_id: str | None


def _run_out(run: Run) -> RunOut:
    result = run.result
    return RunOut(
        id=run.id,
        kind=run.action.kind.value,
        target=run.action.target,
        account_id=run.account_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=result.status.value if result else None,
        signal=result.kind.signal if result else "quiet",
        evidence=[
            EvidenceOut(summary=e.summary, raw_code=e.raw_code)
            for e in (result.evidence if result else ())
        ],
        repair_reason=(
            result.repair_hint.reason if result and result.repair_hint else None
        ),
        repair_action_id=(
            result.repair_hint.action_id if result and result.repair_hint else None
        ),
    )


def _credential_out(hp: CredentialHealth) -> CredentialOut:
    return CredentialOut(
        account_id=hp.account_id,
        kind=hp.kind,
        level=hp.level.value,
        signal=hp.level.signal,
        expires_at=hp.expires_at,
    )


# --- 只读端点（读 = 评估最新健康，事件变更检测保证不重复通知）---


def _account_health(kit, account_id: str):
    return kit.assess_account_health.execute(account_id)


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(request: Request) -> list[AccountOut]:
    """卡名册：账号册账号 ∪ vault 凭据账号，逐账号现场评估健康（A4-01 §2）。"""
    kit = request.app.state.kit
    known: dict[str, object] = {a.id: a for a in kit.accounts.list_all()}
    for hp in kit.vault.health():
        known.setdefault(hp.account_id, None)
    out: list[AccountOut] = []
    for account_id in sorted(known):
        account = known[account_id]
        creds = [hp for hp in kit.vault.health() if hp.account_id == account_id]
        health = _account_health(kit, account_id)
        out.append(
            AccountOut(
                account_id=account_id,
                provider=getattr(account, "provider", "") or "",
                display_name=getattr(account, "display_name", "") or account_id,
                level=health.level.value,
                signal=health.level.signal,
                evidence=list(health.evidence),
                repair_hint=health.repair_hint,
                credentials=[_credential_out(hp) for hp in creds],
            )
        )
    return out


@router.get("/apps", response_model=list[AppOut])
def list_apps(request: Request) -> list[AppOut]:
    """应用名册：连接器能力矩阵（manifest 投影，端零映射）。"""
    registry = request.app.state.registry
    kit = request.app.state.kit
    docked = {a.provider: a.id for a in kit.accounts.list_all()}
    out: list[AppOut] = []
    for app in registry.apps():
        schedule = app.manifest.schedule.get("provision.run")
        out.append(
            AppOut(
                id=app.manifest.id,
                display=app.display,
                capabilities=sorted(app.manifest.capabilities),
                credential_kinds=list(app.manifest.credential.kinds)
                if app.manifest.credential
                else [],
                schedule_times=list(schedule.times) if schedule else [],
                account_id=docked.get(app.manifest.id),
            )
        )
    return out


@router.post("/apps/{target}/import", response_model=ImportOut)
def import_app(target: str, request: Request) -> ImportOut:
    """导入（接入扫描）：扫本机客户端 → 注册卡位 → 凭据入库。

    单家失败不拖累全家族：结果如实分列（accounts/issues），不静默。
    dock 顺带采集（R2-F）：新泊位立即产雷达第一帧；采集失败进 issues，
    绝不打断导入本身（CollectUsage 已把端口异常收进 outcome.error）。
    """
    registry = request.app.state.registry
    kit = request.app.state.kit
    from kabao_connectors.registry import DockContext

    [outcome] = registry.dock(DockContext(vault=kit.vault, register=kit.register_account), target=target)
    for account_id in outcome.accounts:
        collected = kit.collect_usage.execute(target, account_id)
        if collected.error:
            outcome.issues.append(f"用量采集：{collected.error}")
    return ImportOut(target=outcome.target, accounts=outcome.accounts, issues=outcome.issues)


@router.post("/runs", response_model=RunOut)
def create_run(payload: RunIn, request: Request) -> RunOut:
    """发起一次手动领取（provision.run）。窗口按 core 规则（claim_window 单源）。"""
    from kabao_core.application.usecases import RunRequest
    from kabao_core.domain.action import Action, ActionKind
    from kabao_core.domain.schedule import claim_window

    registry = request.app.state.registry
    kit = request.app.state.kit
    try:
        app = registry.get(payload.target)  # 未接入连接器 → 404（显式不静默）
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    entry = next(
        (e for e in registry.schedule_entries() if e["target"] == payload.target), None
    )
    refresh_at = entry["refresh_at"] if entry else "00:00"
    window = claim_window(datetime.now(), refresh_at)
    run = kit.execute_action.execute(
        RunRequest(
            action=Action(kind=ActionKind.PROVISION_RUN, target=payload.target),
            account_id=payload.account_id or f"{payload.target}:main",
            window=window,
            dry_run=payload.dry_run,
            budget=timedelta(seconds=app.provision_budget("provision.run")),
        )
    )
    return _run_out(run)


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 50,
) -> list[RunOut]:
    """领取记录：全库最近 Run，新→旧（A3-01 记录页 M0 版）。"""
    kit = request.app.state.kit
    return [_run_out(run) for run in kit.ledger.list_recent(limit=limit)]


@router.get("/pending", response_model=list[RunOut])
def list_pending(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 50,
) -> list[RunOut]:
    """待处理：attention 结果 Run 聚合——聚合谓词在 core（ListPending，红线 2）。"""
    kit = request.app.state.kit
    return [_run_out(run) for run in kit.list_pending.execute()[:limit]]


# --- R2 用量雷达（三实体投影：快照 / 聚合原话 / 流水，可得性如实分列）---


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
    from kabao_core.domain.usage import forecast_exhaustion

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
