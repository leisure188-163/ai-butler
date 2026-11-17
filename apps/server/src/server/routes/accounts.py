"""卡与凭据域 API（卡名册 + 逐卡健康，A4-01 §2；会话扫描 R5-S1）。

序列化纪律（红线 2）：本模块只做 domain 对象 → JSON 的形状投影，
level / signal / repair_hint 等**语义字面量由 core 出产并原样传递**；
这里没有 if status in [...]，页面谓词交给 kind 驱动。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from butler_core.accounts.domain import CredentialHealth

router = APIRouter(tags=["butler"])


# --- 响应形状（投影，不含语义决策）---


class CredentialOut(BaseModel):
    account_id: str
    kind: str
    level: str  # HealthLevel.value（core 出产字面量）
    signal: str  # HealthLevel.signal（core 出产视觉分类，端零映射）
    expires_at: datetime | None
    revoked: bool  # 本地副本已撤销（ADR-016）；客户端会话不受影响
    revoked_at: datetime | None
    revoked_reason: str


class SessionOut(BaseModel):
    """会话投影：kind/level = core 词表原样（端零映射）。"""

    location: str
    kind: str
    level: str


class AccountOut(BaseModel):
    account_id: str
    account_code: str  # 平台内账号序（ADR-003：target = 平台 + 账号）
    platform_code: str  # 连接器 id（号册归属，A2-01 §1）
    account_name: str  # 平台名（账号册出产）
    level: str  # AssessAccountHealth 出产的五级字面量
    signal: str  # core 出产视觉分类（ok/notice/attention/danger）
    evidence: list[str]
    repair_hint: str | None  # core 出产文案，前端直渲染
    credentials: list[CredentialOut]
    sessions: list[SessionOut]  # R5-S1：已入库会话清单（扫描后随名册可见）


def _credential_out(hp: CredentialHealth) -> CredentialOut:
    return CredentialOut(
        account_id=hp.account_id,
        kind=hp.kind,
        level=hp.level.value,
        signal=hp.level.signal,
        expires_at=hp.expires_at,
        revoked=hp.revoked_at is not None,
        revoked_at=hp.revoked_at,
        revoked_reason=hp.revoked_reason,
    )


# --- 端点（读 = 评估最新健康，事件变更检测保证不重复通知）---


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
        health = kit.assess_account_health.execute(account_id)  # 先评估/撤销，再投影
        creds = [hp for hp in kit.vault.health() if hp.account_id == account_id]
        out.append(
            AccountOut(
                account_id=account_id,
                account_code=getattr(account, "account_code", None)
                or account_id.split(":", 1)[-1],
                platform_code=getattr(account, "platform_code", "") or "",
                account_name=getattr(account, "account_name", "") or account_id,
                level=health.level.value,
                signal=health.level.signal,
                evidence=list(health.evidence),
                repair_hint=health.repair_hint,
                credentials=[_credential_out(hp) for hp in creds],
                sessions=[
                    SessionOut(location=s.location, kind=s.kind.value, level=s.level.value)
                    for s in (getattr(account, "sessions", None) or ())
                ],
            )
        )
    return out


# --- 会话扫描（R5-S1，ADR-013）：只读枚举 + 绑定 + 幂等入库 ---


class SessionsScanOut(BaseModel):
    """扫描结果如实分列：unbound 观测原文回传（绑定不可得不是错误）。"""

    account_id: str
    scanned: int
    added: int
    sessions: list[SessionOut]
    unbound_locations: list[str]


@router.post("/accounts/{account_id}/sessions/scan", response_model=SessionsScanOut)
def scan_account_sessions(account_id: str, request: Request) -> SessionsScanOut:
    """扫一次本机会话并入库（只读枚举；重复扫描幂等）。"""
    kit = request.app.state.kit
    if kit.session_scan is None:
        raise HTTPException(
            status_code=503, detail="该部署未装配会话扫描源（R5-S1 装配口径，如实拒绝）"
        )
    account = kit.accounts.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"卡不存在: {account_id}")
    outcome = kit.session_scan.scan(account.platform_code)
    refreshed = kit.accounts.get(account_id)
    sessions = refreshed.sessions if refreshed else account.sessions
    return SessionsScanOut(
        account_id=account_id,
        scanned=outcome.scanned,
        added=outcome.added,
        sessions=[
            SessionOut(location=s.location, kind=s.kind.value, level=s.level.value)
            for s in sessions
        ],
        unbound_locations=[u.location for u in outcome.unbound],
    )
