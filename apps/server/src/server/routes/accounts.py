"""卡与凭据域 API（卡名册 + 逐卡健康，A4-01 §2；会话扫描 R5-S1）。

序列化纪律（红线 2）：本模块只做 domain 对象 → JSON 的形状投影，
level / signal / repair_hint 等**语义字面量由 core 出产并原样传递**；
这里没有 if status in [...]，页面谓词交给 kind 驱动。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from butler_core.accounts.domain import (
    AccountAlreadyExists,
    AccountInvalid,
    AccountIdentity,
    CredentialHealth,
    Secret,
    account_label,
)

router = APIRouter(tags=["butler"])


# --- 响应形状（投影，不含语义决策）---


class CredentialOut(BaseModel):
    account_id: str
    kind: str
    slot: str  # 凭据槽位（ADR-033）：default / 主 key / 备用 key…
    label: str  # 槽位显示名（空 = 前端显示 slot）
    level: str  # HealthLevel.value（core 出产字面量）
    signal: str  # HealthLevel.signal（core 出产视觉分类，端零映射）
    expires_at: datetime | None
    revoked: bool  # 本地副本已撤销（ADR-016）；客户端会话不受影响
    revoked_at: datetime | None
    revoked_reason: str


class IdentityOut(BaseModel):
    """真实身份投影（ADR-033）：只显示/匹配，不参与编址。"""

    nickname: str = ""
    email: str = ""
    uid: str = ""
    org: str = ""
    source_key: str = ""


class SessionOut(BaseModel):
    """会话投影：kind/level = core 词表原样（端零映射）。"""

    location: str
    kind: str
    level: str


class AccountOut(BaseModel):
    account_id: str
    account_code: str  # 人工维护的后缀（可空 = 尚未关联登录账户，ADR-034 §5）
    platform_code: str  # 连接器 id（号册归属，A2-01 §1）
    account_name: str  # 账户自己的显示信息（不含平台名，ADR-034 §5）
    account_label: str  # 显示标签：core 单源计算（ADR-033；前端不再自行拼装）
    alias: str  # 用户别名（ADR-030）：非空时前端优先显示，取不到真实身份的平台靠它对上号
    identity: IdentityOut  # 真实身份（ADR-033）：昵称/邮箱/uid/source_key
    origin: str  # connector=连接器导入 / manual=用户手建
    base_url: str  # 账户级 API 基址（空 = 用接入源缺省）
    active: bool  # 用户管理开关
    last_seen_at: datetime | None  # 最近一次连接器看到该账户
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
        slot=hp.slot,
        label=hp.label,
        level=hp.level.value,
        signal=hp.level.signal,
        expires_at=hp.expires_at,
        revoked=hp.revoked_at is not None,
        revoked_at=hp.revoked_at,
        revoked_reason=hp.revoked_reason,
    )


def _identity_out(identity: AccountIdentity | None) -> IdentityOut:
    if identity is None:
        return IdentityOut()
    return IdentityOut(
        nickname=identity.nickname,
        email=identity.email,
        uid=identity.uid,
        org=identity.org,
        source_key=identity.source_key,
    )


def _account_out(account_id: str, account: object, kit) -> AccountOut:
    """单账户投影：健康现场评估 + 凭据/会话并账（读取端点与编辑端点共用）。"""
    health = kit.assess_account_health.execute(account_id)  # 先评估/撤销，再投影
    creds = [hp for hp in kit.vault.health() if hp.account_id == account_id]
    return AccountOut(
        account_id=account_id,
        account_code=getattr(account, "account_code", "") or "",
        platform_code=getattr(account, "platform_code", "") or "",
        account_name=getattr(account, "account_name", "") or account_id,
        account_label=account_label(account),
        alias=getattr(account, "alias", "") or "",
        identity=_identity_out(getattr(account, "identity", None)),
        origin=getattr(account, "origin", "connector") or "connector",
        base_url=getattr(account, "base_url", "") or "",
        active=bool(getattr(account, "is_active", True)),
        last_seen_at=getattr(account, "last_seen_at", None),
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


# --- 端点（读 = 评估最新健康，事件变更检测保证不重复通知）---


class AccountDeletedOut(BaseModel):
    """删除账户结果（2026-11-19）：账户行 + 关联凭据一并清掉。"""

    account_id: str
    credentials_deleted: int
    message: str


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(request: Request) -> list[AccountOut]:
    """账户名册：**只读 `acc_account`**（2026-11-19 用户裁决）。

    此前是「账户册 ∪ vault 凭据账号」，导致删掉账户行后凭据仍把它顶成幽灵账户；
    现在凭据只作为账户的附属投影，不再单独造账户行——账户数据的唯一真相源是账户表。
    """
    kit = request.app.state.kit
    rows = kit.accounts.list_all()
    return [_account_out(a.id, a, kit) for a in rows]


@router.delete("/accounts/{account_id}", response_model=AccountDeletedOut)
def delete_account(account_id: str, request: Request) -> AccountDeletedOut:
    """删除账户（2026-11-19 用户裁决）：账户行 + 关联凭据一并删除，不留脏数据。

    确认弹层的「还有 N 条关联凭据」由前端按 `AccountOut.credentials` 明示；
    这里返回实际清掉的条数。账户不存在 = 404（不会误清同名凭据）。
    """
    kit = request.app.state.kit
    purged = kit.delete_account.execute(account_id)
    if purged is None:
        raise HTTPException(status_code=404, detail=f"账户不存在：{account_id}")
    return AccountDeletedOut(
        account_id=account_id,
        credentials_deleted=purged,
        message=f"已删除账户与 {purged} 条关联凭据" if purged else "已删除账户（无关联凭据）",
    )


# --- 手建账户 / 编辑 / 凭据槽位（ADR-033）---

ALIAS_MAX = 40
ACCOUNT_NAME_MAX = 60


class IdentityIn(BaseModel):
    """真实身份写入（ADR-033）：全部可选，空值 = 未知。"""

    nickname: str | None = None
    email: str | None = None
    uid: str | None = None
    org: str | None = None
    source_key: str | None = None


class AccountCreateIn(BaseModel):
    """手建账户（ADR-035）：account_code 是可空人工后缀，不再自动生成。"""

    platform_code: str
    account_code: str | None = None
    account_name: str
    alias: str = ""
    base_url: str = ""
    identity: IdentityIn | None = None
    kind: str | None = None
    secret: str | None = None
    slot: str = "default"
    label: str = ""
    expires_at: datetime | None = None


class AccountPatchIn(BaseModel):
    """账户编辑（ADR-035）：显示/运营字段 + 人工后缀；account_id 不可改写。"""

    alias: str | None = None  # 空串 = 清除别名
    account_name: str | None = None
    account_code: str | None = None  # 空串 = 清空人工后缀（回到未关联）
    active: bool | None = None
    base_url: str | None = None  # 空串 = 回落接入源缺省
    identity: IdentityIn | None = None


class CredentialIn(BaseModel):
    """追加凭据槽位（ADR-033）：同账户同 kind 可多份，slot 缺省 = default。"""

    kind: str
    secret: str
    slot: str = "default"
    label: str = ""
    expires_at: datetime | None = None


class CredentialRevokedOut(BaseModel):
    account_id: str
    kind: str
    slot: str
    revoked: bool


def _clean_identity(body: IdentityIn | None, base: AccountIdentity | None = None) -> AccountIdentity:
    """None 字段 = 沿用 base；空串 = 显式未知（可清空）。"""
    if body is None:
        return base or AccountIdentity()
    old = base or AccountIdentity()
    fields = body.model_fields_set
    return AccountIdentity(
        nickname=body.nickname.strip() if "nickname" in fields and body.nickname is not None else old.nickname,
        email=body.email.strip() if "email" in fields and body.email is not None else old.email,
        uid=body.uid.strip() if "uid" in fields and body.uid is not None else old.uid,
        org=body.org.strip() if "org" in fields and body.org is not None else old.org,
        source_key=(
            body.source_key.strip()
            if "source_key" in fields and body.source_key is not None
            else old.source_key
        ),
    )


def _account_or_404(kit, account_id: str):
    account = kit.accounts.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"账户不存在：{account_id}")
    return account


def _platform_or_404(kit, platform_code: str):
    platform = kit.platforms.get(platform_code)
    if platform is None or platform.deprecated_at is not None:
        raise HTTPException(
            status_code=404,
            detail=f"平台不存在或已退役：{platform_code}（先导入平台或创建接入源）",
        )
    return platform


def _validate_alias(alias: str) -> str:
    cleaned = alias.strip()
    if len(cleaned) > ALIAS_MAX:
        raise HTTPException(status_code=400, detail=f"别名过长（≤{ALIAS_MAX}）")
    return cleaned


def _validate_base_url(base_url: str) -> str:
    cleaned = base_url.strip()
    if cleaned and not cleaned.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="base_url 必须以 http:// 或 https:// 开头")
    return cleaned


@router.post("/accounts", response_model=AccountOut)
def create_account(body: AccountCreateIn, request: Request) -> AccountOut:
    """手建账户（ADR-035）：API 型接入源、连接器没扫到的小号都从这里进。

    account_code 是可空的人工后缀：空 = 尚未关联登录账户；非空时平台内唯一。
    首份凭据同请求写入（kind/secret 必须成对）；凭据写失败不产生半成品账户。
    """
    kit = request.app.state.kit
    platform = _platform_or_404(kit, body.platform_code.strip())
    name = body.account_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="account_name 不能为空")
    if len(name) > ACCOUNT_NAME_MAX:
        raise HTTPException(status_code=400, detail=f"account_name 过长（≤{ACCOUNT_NAME_MAX}）")
    alias = _validate_alias(body.alias)
    base_url = _validate_base_url(body.base_url)
    code = (body.account_code or "").strip()
    kind = (body.kind or "").strip()
    secret = None
    if body.secret is not None:
        if not body.secret:
            raise HTTPException(status_code=400, detail="凭据明文不能为空")
        if not kind:
            raise HTTPException(status_code=400, detail="带凭据创建账户时必须声明 kind")
        secret = Secret(body.secret)
    elif kind:
        raise HTTPException(status_code=400, detail="声明了 kind 但未提供明文凭据")
    if kind and platform.credential_kinds and kind not in platform.credential_kinds:
        raise HTTPException(
            status_code=400,
            detail=f"平台 {platform.platform_code} 未申报该凭据类型：{kind}",
        )
    if body.label and len(body.label) > 40:
        raise HTTPException(status_code=400, detail="凭据标签过长（≤40）")

    try:
        account = kit.create_account.execute(
            platform.platform_code,
            code,
            name,
            alias=alias,
            base_url=base_url,
            identity=_clean_identity(body.identity),
            kind=kind,
            secret=secret,
            slot=body.slot,
            label=body.label.strip(),
            expires_at=body.expires_at,
        )
    except AccountAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _account_out(account.id, account, kit)


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def patch_account(account_id: str, body: AccountPatchIn, request: Request):
    """编辑账户（ADR-035）：别名 / 显示名 / 人工后缀 / 启停 / 地址 / 真实身份。

    只改显示与运营列：account_id / platform_code / origin 不可改写；
    account_code 是可空人工后缀，允许后续关联登录账户时补齐或清空。
    """
    kit = request.app.state.kit
    account = _account_or_404(kit, account_id)
    fields = body.model_fields_set
    kwargs: dict[str, object] = {}
    if "alias" in fields:
        kwargs["alias"] = _validate_alias(body.alias or "")
    if "account_name" in fields and body.account_name is not None:
        name = body.account_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="account_name 不能改为空")
        if len(name) > ACCOUNT_NAME_MAX:
            raise HTTPException(status_code=400, detail=f"account_name 过长（≤{ACCOUNT_NAME_MAX}）")
        kwargs["account_name"] = name
    if "active" in fields and body.active is not None:
        kwargs["active"] = body.active
    if "base_url" in fields:
        kwargs["base_url"] = _validate_base_url(body.base_url or "")
    if body.identity is not None:
        kwargs["identity"] = _clean_identity(body.identity, account.identity)
    # 字段名投影：端侧契约用 active，core 用 is_active
    if "active" in kwargs:
        kwargs["is_active"] = kwargs.pop("active")
    try:
        updated = kit.update_account.execute(account_id, **kwargs)
    except AccountAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AccountInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _account_out(account_id, updated, kit)


@router.post("/accounts/{account_id}/credentials", response_model=CredentialOut)
def add_account_credential(
    account_id: str, body: CredentialIn, request: Request
) -> CredentialOut:
    """追加一个凭据槽位（ADR-033）：同 kind 多份 key 用 slot 区分。"""
    kit = request.app.state.kit
    account = _account_or_404(kit, account_id)
    platform = kit.platforms.get(account.platform_code)
    kind = body.kind.strip()
    if not kind:
        raise HTTPException(status_code=400, detail="kind 不能为空")
    if not body.secret:
        raise HTTPException(status_code=400, detail="凭据明文不能为空")
    if platform is not None and platform.credential_kinds and kind not in platform.credential_kinds:
        raise HTTPException(
            status_code=400,
            detail=f"平台 {platform.platform_code} 未申报该凭据类型：{kind}",
        )
    if body.label and len(body.label) > 40:
        raise HTTPException(status_code=400, detail="凭据标签过长（≤40）")
    try:
        credential = kit.add_credential.execute(
            account_id,
            kind,
            Secret(body.secret),
            slot=body.slot,
            label=body.label.strip(),
            expires_at=body.expires_at,
        )
    except AccountInvalid as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    hp = next(
        (
            h
            for h in kit.vault.health()
            if h.account_id == account_id and h.kind == kind and h.slot == credential.slot
        ),
        None,
    )
    if hp is None:  # 写后读不到 = 存储层异常，显式报不假装成功
        hp = CredentialHealth.build(
            account_id=account_id,
            kind=kind,
            slot=credential.slot,
            label=credential.label,
            expires_at=body.expires_at,
        )
    return _credential_out(hp)


@router.delete(
    "/accounts/{account_id}/credentials/{kind}/{slot}", response_model=CredentialRevokedOut
)
def revoke_account_credential(
    account_id: str, kind: str, slot: str, request: Request
) -> CredentialRevokedOut:
    """撤销单个凭据槽位（ADR-033）：归档旧值、清主引用，客户端会话不受影响。"""
    kit = request.app.state.kit
    _account_or_404(kit, account_id)
    revoked = kit.revoke_credential.execute(account_id, kind, slot=slot)
    if not revoked:
        raise HTTPException(
            status_code=404, detail=f"凭据槽位不存在或已撤销：{kind}@{slot}"
        )
    return CredentialRevokedOut(account_id=account_id, kind=kind, slot=slot, revoked=True)


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
