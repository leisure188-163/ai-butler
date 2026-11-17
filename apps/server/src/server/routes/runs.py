"""运行台账域 API（手动动作发起 + Run 记录 + 待处理聚合）。

响应里的 status / signal / repair 字面量全部 core 出产原样传递（红线 2）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from butler_core.execution.domain import Run

router = APIRouter(tags=["butler"])

logger = logging.getLogger(__name__)

_MAX_LIMIT = 200


def _assess_after_run(kit, account_id: str) -> None:
    """动作落地后即时评估健康（ADR-015）：登录态失效立刻进待办 + 发事件。

    评估失败只记日志，不回滚也不改变已落账的执行结果（通知是副作用）。
    """
    try:
        kit.assess_account_health.execute(account_id)
    except Exception:
        logger.exception("动作后健康评估失败（已隔离，Run 台账不受影响）")


class RunIn(BaseModel):
    """手动动作入参：target 必填；kind 缺省 = provision.run（领取）；
    health.check = 体检探针（R3 网页通道，A2-03 §3，免窗口）。"""

    target: str
    kind: str = "provision.run"
    account_id: str | None = None  # 显式账号规范 id（优先于 account_key）
    account_key: str = "main"  # ADR-003：target = 应用 + 账号；裸应用 id 兼容首账号
    dry_run: bool = False


class EvidenceOut(BaseModel):
    summary: str
    raw_code: str | None = None


class RunOut(BaseModel):
    id: str
    kind: str  # ActionKind.value
    target: str
    account_id: str
    account_key: str  # 幂等键按账号粒度（ADR-003 §4）
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
        account_key=run.account_id.split(":", 1)[-1],
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


@router.post("/runs", response_model=RunOut)
def create_run(payload: RunIn, request: Request) -> RunOut:
    """发起一次手动动作：provision.run（领取）/ health.check（体检探针，R3）。

    kind ∈ ActionKind 词表校验；health.check 免窗口（非领取类写动作，无幂等键），
    预算取连接器 health.check 能力申报的 budget_seconds。
    """
    from butler_core.accounts.domain import account_identity
    from butler_core.execution.usecases.execute_action import RunRequest
    from butler_core.execution.domain import Action, ActionKind
    from butler_core.scheduling.domain import claim_window

    resolved_account = payload.account_id or account_identity(
        payload.target, payload.account_key
    )
    registry = request.app.state.registry
    kit = request.app.state.kit
    try:
        app = registry.get(payload.target)  # 未接入连接器 → 404（显式不静默）
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        kind = ActionKind(payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"未知动作 kind: {payload.kind!r}") from exc

    if kind is ActionKind.HEALTH_CHECK:
        if app.manifest.capabilities.get("health.check") is None:
            raise HTTPException(
                status_code=422, detail=f"{payload.target} 未申报 health.check 能力"
            )
        run = kit.execute_action.execute(
            RunRequest(
                action=Action(kind=kind, target=payload.target),
                account_id=resolved_account,
                budget=timedelta(seconds=app.provision_budget("health.check")),
            )
        )
        _assess_after_run(kit, resolved_account)
        return _run_out(run)
    if kind is not ActionKind.PROVISION_RUN:
        raise HTTPException(
            status_code=422,
            detail=f"动作 {kind.value} 不支持手动发起（仅 provision.run / health.check）",
        )

    entry = next(
        (e for e in registry.schedule_entries() if e["target"] == payload.target), None
    )
    refresh_at = entry["refresh_at"] if entry else "00:00"
    window = claim_window(datetime.now(), refresh_at)
    run = kit.execute_action.execute(
        RunRequest(
            action=Action(kind=ActionKind.PROVISION_RUN, target=payload.target),
            account_id=resolved_account,
            window=window,
            dry_run=payload.dry_run,
            budget=timedelta(seconds=app.provision_budget("provision.run")),
        )
    )
    _assess_after_run(kit, resolved_account)
    return _run_out(run)


@router.post("/runs/claim-all", response_model=list[RunOut])
def claim_all_runs(request: Request) -> list[RunOut]:
    """一键领取：全部已泊位卡逐张发起领取（窗口按 core 时间表规则；同窗口幂等回放）。

    只认已泊位的（卡包里有的卡才领）；端零入参，选卡语义归编排层。
    """
    from butler_core.execution.usecases.execute_action import RunRequest
    from butler_core.execution.domain import Action, ActionKind
    from butler_core.scheduling.domain import claim_window

    registry = request.app.state.registry
    kit = request.app.state.kit
    # 多账号（ADR-003）：同一应用下每个账户各自发起，幂等键按账号粒度
    docked: dict[str, list[str]] = {}
    for account in kit.accounts.list_all():
        docked.setdefault(account.app, []).append(account.id)
    refresh = {e["target"]: e["refresh_at"] for e in registry.schedule_entries()}
    out: list[RunOut] = []
    for app in registry.apps():
        if app.manifest.capabilities.get("provision.run") is None:
            continue  # 网页连接器无领取概念（A1-04 §6），一键领取跳过
        for account_id in docked.get(app.manifest.id, []):
            window = claim_window(datetime.now(), refresh.get(app.manifest.id, "00:00"))
            run = kit.execute_action.execute(
                RunRequest(
                    action=Action(kind=ActionKind.PROVISION_RUN, target=app.manifest.id),
                    account_id=account_id,
                    window=window,
                    budget=timedelta(seconds=app.provision_budget("provision.run")),
                )
            )
            out.append(_run_out(run))
            _assess_after_run(kit, account_id)
    return out


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
