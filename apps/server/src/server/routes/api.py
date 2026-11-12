"""Kabao 领域 API（M0 三页数据源）：账号 / 领取记录 / 待处理。

序列化纪律（红线 2）：本模块只做 domain 对象 → JSON 的形状投影，
level / status / repair_hint 等**语义字面量由 core 出产并原样传递**；
这里没有 if status in [...]，页面谓词交给 kind 驱动。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from kabao_core.domain.run import Run
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
    """
    registry = request.app.state.registry
    kit = request.app.state.kit
    from kabao_connectors.registry import DockContext

    [outcome] = registry.dock(DockContext(vault=kit.vault, register=kit.register_account), target=target)
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
