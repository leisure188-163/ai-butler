"""账户域（A2-04）：Platform / Account 集合 / 凭据事实。

多账号（ADR-003）：一 Platform 挂 N 个 Account，身份 = (platform, account_code)；
平台事实本身归 platforms 域（A2-09，ADR-022），本域只落 platform_code 引用；
凭据/权益/会话全部挂 account_id。凭据明文载体 Secret 与保险库引用也在本域
——健康分级枚举来自 shared 内核，域之间不互依（A1-05 §2 依赖恒等式）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Callable

from butler_core.shared.errors import DomainError
from butler_core.shared.health_level import HealthLevel, credential_level
from butler_core.shared.time import now_utc

DEFAULT_ACCOUNT_CODE = "main"  # 仅存量/兼容编址用；新账户不再自动生成 code
DEFAULT_CREDENTIAL_SLOT = "default"
EXPIRING_WINDOW_DAYS = 3  # CREDENTIAL_EXPIRING 预警窗（旧值不变，A2-07 §2）

#: 账户来源（ADR-033）：connector=连接器扫描导入 / manual=用户在账户页手建。
ACCOUNT_ORIGINS = ("connector", "manual")

#: 人工后缀（ADR-035）：可空；非空时不含空白与冒号，长度 ≤32。
_CODE_PATTERN = re.compile(r"^[^\s:]{1,32}$")

#: 凭据槽位形状（ADR-033）：槽位进后端引用，禁止分隔符与空白。
_SLOT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
_LABEL_MAX = 40


class AccountInvalid(DomainError):
    """账户身份或凭据形状非法——显式拒绝（红线 5）。"""


class AccountAlreadyExists(AccountInvalid):
    """(platform, account_code) 或 (platform, source_key) 已存在——不静默改号。"""


class AccountConflict(AccountInvalid):
    """同一个平台内 code 命中但稳定身份不同——显式冲突，禁止把两个人并成一张卡。"""


class EmptySecret(DomainError):
    """空明文入库 = 拒绝执行（红线 5）。"""


def validate_account_code(account_code: str) -> str:
    """人工后缀校验（ADR-035）：空 = 尚未关联登录账户；非空才要求合法短标识。"""

    code = account_code.strip()
    if not code:
        return ""
    if not _CODE_PATTERN.match(code):
        raise AccountInvalid(
            f"account_code {code!r} 非法（人工后缀不能含空白或冒号，≤32 位；"
            "空串表示尚未关联）"
        )
    return code


def account_identity(platform: str, account_code: str = DEFAULT_ACCOUNT_CODE) -> str:
    """账户规范 id：``{platform}:{account_code}``——全库唯一锚点单源。"""

    if not platform.strip():
        raise AccountInvalid("platform（connector id）不能为空")
    if not account_code.strip() or ":" in account_code:
        raise AccountInvalid("account_code 非空且不含冒号")
    return f"{platform.strip()}:{account_code.strip()}"


def main_account_id(platform: str) -> str:
    """兼容名：首账号（main）的规范 id——与存量 `:main` 编址零迁移兼容。"""

    return account_identity(platform, DEFAULT_ACCOUNT_CODE)


@dataclass(frozen=True)
class Platform:
    """Connector 的产品级身份，不进 UI 导航（下沉为实现细节）。"""

    id: str
    display: str


@dataclass(frozen=True)
class AccountIdentity:
    """账户的真实身份（ADR-033）：只做显示与匹配，**不参与编址**。

    source_key 是连接器侧稳定身份键（抖音 sec_uid / Qoder user.id / Trae userId）；
    取不到时留空 = 如实未知，禁止用昵称兜底匹配。"""

    nickname: str = ""
    email: str = ""
    uid: str = ""
    org: str = ""
    source_key: str = ""

    def __post_init__(self) -> None:
        for name in ("nickname", "email", "uid", "org", "source_key"):
            value = getattr(self, name)
            if len(value) > 200:
                raise AccountInvalid(f"AccountIdentity.{name} 过长（≤200）")
            if "\n" in value or "\r" in value:
                raise AccountInvalid(f"AccountIdentity.{name} 不能含换行")

    @property
    def is_empty(self) -> bool:
        return not any((self.nickname, self.email, self.uid, self.org, self.source_key))


def _validate_slot(slot: str) -> str:
    slot = slot.strip()
    if not _SLOT_PATTERN.match(slot):
        raise AccountInvalid(
            f"凭据槽位 {slot!r} 非法（只允许字母/数字/下划线/连字符，1–24 位）"
        )
    return slot


@dataclass(frozen=True)
class Credential:
    """凭据元数据（明文在 vault，core 只见句柄与有效期）。

    slot（ADR-033）：同账户同 kind 的多份凭据（主 key / 备用 key / 多租户）；
    `default` 槽保持旧后端引用 `{account}:{kind}`，存量秘密零迁移。
    label 只做显示，不参与寻址。"""

    account_id: str
    kind: str
    slot: str = DEFAULT_CREDENTIAL_SLOT
    label: str = ""
    expires_at: datetime | None = None
    rotated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.account_id.strip() or not self.kind.strip():
            raise AccountInvalid("Credential 必须绑定非空 account_id 与 kind")
        object.__setattr__(self, "slot", _validate_slot(self.slot))
        if len(self.label) > _LABEL_MAX or "\n" in self.label:
            raise AccountInvalid(f"Credential.label 过长或含换行（≤{_LABEL_MAX}）")


@dataclass(frozen=True)
class Entitlement:
    """权益：余额 / 连签 / 上次领取窗口（按账号隔离）。"""

    account_id: str
    balance: str = ""
    streak: int = 0
    last_claim_window: str = ""


class SessionKind(StrEnum):
    """会话种类（ADR-013 裁决 1）：迁移对象按 kind 分列，词表单源。"""

    WORKSPACE = "workspace"  # 工作区/配置上下文（纯文件，R5 首批迁移对象）
    CONVERSATION = "conversation"  # 对话历史（写风险高，逐家取证后再开）


class SessionLevel(StrEnum):
    """可迁移级别（A1-01 §3 L4）：local=本地文件迁移 / inject=摘要注入 /
    server=官方共享能力。产品承诺口径 = 可迁移+可回退，不承诺无缝。"""

    LOCAL = "local"
    INJECT = "inject"
    SERVER = "server"


@dataclass(frozen=True)
class Session:
    """本机会话：存储位置 + 种类 + 可迁移级别（R5-S1，ADR-013）。"""

    account_id: str
    location: str
    kind: SessionKind
    level: SessionLevel = SessionLevel.LOCAL

    def __post_init__(self) -> None:
        if not self.account_id.strip() or not self.location.strip():
            raise AccountInvalid("会话需要非空的 account_id 与 location")


@dataclass(frozen=True)
class SessionSighting:
    """一次只读扫描的会话观测（扫描器出产，非持久实体）。

    device_ref = 供应商侧账户标识（trae = Aha 数字设备号，即 state.vscdb
    key 前缀）；绑定不可得时如实为 None——不猜归属。"""

    location: str
    kind: SessionKind
    level: SessionLevel = SessionLevel.LOCAL
    device_ref: str | None = None


@dataclass(frozen=True)
class Account:
    """账户聚合根（集合语义）：Run / Event / Sample / 凭据全挂 account_id。

    account_id（ADR-034）：不透明、不可变的账户指针（新账户 ``acc_<8hex>``）；
    展示/匹配走 account_name/alias/identity，**不再从平台或昵称推导 id**。
    account_code（ADR-035）：人工维护的短后缀，可空；同步账户不生成，等用户
    后续关联登录账户时再补。存量 ``{platform}:{code}`` 仅作为历史主键保留。
    """

    id: str
    platform_code: str
    account_name: str
    created_at: datetime
    account_code: str = ""
    credentials: tuple[Credential, ...] = ()
    entitlement: Entitlement | None = None
    sessions: tuple[Session, ...] = ()
    deleted_at: datetime | None = None
    base_url: str = ""  # 账户级 API 基址（Qoder CN/Global 双 host 事实落库；空 = 用连接器缺省）
    device_ref: str | None = None  # 供应商侧账户标识绑定；绑定不可得 = 如实 None（A2-04 §4.1）
    is_active: bool = True  # 用户管理开关（不用 enabled——数据库关键字风险；停用是运营动作，健康熔断仍归 health 域，A2-04 §6）
    alias: str = ""  # 用户别名（ADR-030）：连接器取不到真实身份时（如 trae_cn）人工命名，显示优先于 account_name
    identity: AccountIdentity = field(default_factory=AccountIdentity)  # 真实身份（ADR-033）：只显示/匹配，不进编址
    origin: str = "connector"  # connector=连接器导入 / manual=用户手建（ACCOUNT_ORIGINS）
    last_seen_at: datetime | None = None  # 最近一次连接器看到该账户（运营字段）

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.platform_code.strip():
            raise AccountInvalid("Account 需要非空 id 与 platform")
        if not self.account_name.strip():
            raise AccountInvalid("Account 需要非空 account_name")
        if len(self.alias) > 40 or "\n" in self.alias:
            raise AccountInvalid("Account.alias 过长或含换行（≤40）")
        if self.origin not in ACCOUNT_ORIGINS:
            raise AccountInvalid(
                f"Account origin={self.origin!r} 不在词表 {ACCOUNT_ORIGINS}"
            )
        prefix = f"{self.platform_code.strip()}:"
        if self.id.startswith(prefix):
            # 存量行/旧适配器只带复合 id 时，从 ``{platform}:{code}`` 反推 code；
            # 新账户 id 不透明（acc_xxx），不做任何推导。
            suffix = self.id[len(prefix):]
            if not suffix or ":" in suffix:
                raise AccountInvalid(
                    f"Account id {self.id!r} 形状非法：{self.platform_code} 后的 code 为空或含冒号"
                )
            object.__setattr__(self, "account_code", suffix)
        for cred in self.credentials:
            if cred.account_id != self.id:
                raise AccountInvalid("凭据必须绑定本平台账户，禁止跨平台共享")
        if self.account_code:
            object.__setattr__(
                self, "account_code", validate_account_code(self.account_code)
            )

    @property
    def address(self) -> tuple[str, str]:
        """编址（ADR-033 用语）：(platform_code, account_code)，创建后冻结。"""

        return (self.platform_code, self.account_code)


def account_label(account: Account) -> str:
    """账户显示标签（ADR-035）：只显示账户自身信息，不拼平台名。

    优先级：alias > identity.nickname > account_name > account_code > account_id。
    account_type/平台名由列表分组展示，不进账户名。
    """

    if account.alias.strip():
        return account.alias.strip()
    if account.identity.nickname.strip():
        return account.identity.nickname.strip()
    name = account.account_name.strip()
    if name:
        return name
    return account.account_code.strip() or account.id


@dataclass(frozen=True)
class Secret:
    """唯一合法的明文载体：repr/str 永远 [REDACTED]（A4-01 §1）。"""

    _value: str

    def __post_init__(self) -> None:
        if self._value == "":
            raise EmptySecret("Secret 明文不能为空——空值是配置事故，不静默")

    def expose(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "[REDACTED]"

    def __str__(self) -> str:
        return "[REDACTED]"


def vault_ref(account_id: str, kind: str, slot: str = DEFAULT_CREDENTIAL_SLOT) -> str:
    """保险库引用 = (account_id, kind, slot) 的规范串（ADR-033）。

    默认槽保持旧形状 `{account}:{kind}`——存量秘密与旧归档引用零迁移；
    非默认槽用 `{account}:{kind}@{slot}`，轮换归档再追加 `#{seq}`。
    """

    if not account_id.strip() or kind.strip() == "":
        raise DomainError("vault ref 需要非空的 account_id 与 kind")
    slot = _validate_slot(slot)
    base = f"{account_id}:{kind}"
    return base if slot == DEFAULT_CREDENTIAL_SLOT else f"{base}@{slot}"


@dataclass(frozen=True)
class CredentialHealth:
    """vault.health() 出品：喂给健康域与"待处理"列表（A4-01 §1）。

    revoked_at 非空 = 本地副本已撤销（凭据不可用、等待重新停靠）；
    客户端自己的登录态不受影响（ADR-016）。
    """

    account_id: str
    kind: str
    slot: str = DEFAULT_CREDENTIAL_SLOT
    label: str = ""
    expires_at: datetime | None = None
    level: HealthLevel = HealthLevel.HEALTHY
    revoked_at: datetime | None = None
    revoked_reason: str = ""
    stored_at: datetime | None = None  # 最近一次停靠/轮换写入时间（旧连败不计新凭据）

    @classmethod
    def build(
        cls,
        *,
        account_id: str,
        kind: str,
        expires_at: datetime | None,
        clock: Callable[[], datetime] = now_utc,
        warn_window_days: int = EXPIRING_WINDOW_DAYS,
        revoked_at: datetime | None = None,
        revoked_reason: str = "",
        stored_at: datetime | None = None,
        slot: str = DEFAULT_CREDENTIAL_SLOT,
        label: str = "",
    ) -> "CredentialHealth":
        """分级谓词在 shared 内核单源重算——适配器只交数据。"""

        return cls(
            account_id=account_id,
            kind=kind,
            slot=_validate_slot(slot),
            label=label,
            expires_at=expires_at,
            level=credential_level(expires_at, clock(), warn_window_days=warn_window_days),
            revoked_at=revoked_at,
            revoked_reason=revoked_reason,
            stored_at=stored_at,
        )


@dataclass(frozen=True)
class CachePolicy:
    """凭据池缓存策略（ADR-012 裁决 3）：策略 = kind 数据，非 per-platform 分支。

    ttl_seconds = 0 表示该 kind 不缓存（严格现用现取）；未声明的 kind 一律
    按不缓存处理（保守默认）。网关热路径按 kind 声明 TTL（引擎装配注入）。"""

    kind: str
    ttl_seconds: float = 0.0


@dataclass(frozen=True)
class AccountDraft:
    """注册用例的入参形状（避免在用例签名里堆参数）。"""

    platform: str
    account_name: str
    account_code: str = ""
    credentials: tuple[Credential, ...] = field(default_factory=tuple)
