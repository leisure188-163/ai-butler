"""卡与凭据域 API（卡名册 + 逐卡健康，A4-01 §2）。

序列化纪律（红线 2）：本模块只做 domain 对象 → JSON 的形状投影，
level / signal / repair_hint 等**语义字面量由 core 出产并原样传递**；
这里没有 if status in [...]，页面谓词交给 kind 驱动。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
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


class AccountOut(BaseModel):
    account_id: str
    account_key: str  # 应用内账号序（ADR-008：target = 应用 + 账号）
    provider: str  # 连接器 id（号册归属，A2-01 §1）
    display_name: str  # 应用名（账号册出产）
    level: str  # AssessAccountHealth 出产的五级字面量
    signal: str  # core 出产视觉分类（ok/notice/attention/danger）
    evidence: list[str]
    repair_hint: str | None  # core 出产文案，前端直渲染
    credentials: list[CredentialOut]


def _credential_out(hp: CredentialHealth) -> CredentialOut:
    return CredentialOut(
        account_id=hp.account_id,
        kind=hp.kind,
        level=hp.level.value,
        signal=hp.level.signal,
        expires_at=hp.expires_at,
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
        creds = [hp for hp in kit.vault.health() if hp.account_id == account_id]
        health = kit.assess_account_health.execute(account_id)
        out.append(
            AccountOut(
                account_id=account_id,
                account_key=getattr(account, "account_key", None)
                or account_id.split(":", 1)[-1],
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
