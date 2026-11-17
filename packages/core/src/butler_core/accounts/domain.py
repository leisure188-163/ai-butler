"""账户域（A2-04）：Platform / Account 集合 / 凭据事实。

多账号（ADR-003）：一 Platform 挂 N 个 Account，身份 = (platform, account_code)；
凭据/权益/会话全部挂 account_id。凭据明文载体 Secret 与保险库引用也在本域
——健康分级枚举来自 shared 内核，域之间不互依（A1-05 §2 依赖恒等式）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Callable

from butler_core.shared.errors import DomainError
from butler_core.shared.health_level import HealthLevel, credential_level
from butler_core.shared.time import now_utc

DEFAULT_ACCOUNT_CODE = "main"
EXPIRING_WINDOW_DAYS = 3  # CREDENTIAL_EXPIRING 预警窗（旧值不变，A2-07 §2）


class AccountInvalid(DomainError):
    """账户身份或凭据形状非法——显式拒绝（红线 5）。"""


class AccountAlreadyExists(AccountInvalid):
    """(platform, account_code) 已存在且事实冲突——不静默改号。"""


class EmptySecret(DomainError):
    """空明文入库 = 拒绝执行（红线 5）。"""


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
class Credential:
    """凭据元数据（明文在 vault，core 只见句柄与有效期）。"""

    account_id: str
    kind: str
    expires_at: datetime | None = None
    rotated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.account_id.strip() or not self.kind.strip():
            raise AccountInvalid("Credential 必须绑定非空 account_id 与 kind")


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
    """账户聚合根（集合语义）：Run / Event / Sample / 凭据全挂 account_id。"""

    id: str
    platform_code: str
    account_name: str
    created_at: datetime
    account_code: str = DEFAULT_ACCOUNT_CODE
    credentials: tuple[Credential, ...] = ()
    entitlement: Entitlement | None = None
    sessions: tuple[Session, ...] = ()
    deleted_at: datetime | None = None
    base_url: str = ""  # 账户级 API 基址（Qoder CN/Global 双 host 事实落库；空 = 用连接器缺省）
    device_ref: str | None = None  # 供应商侧账户标识绑定；绑定不可得 = 如实 None（A2-04 §4.1）
    is_active: bool = True  # 用户管理开关（不用 enabled——数据库关键字风险；停用是运营动作，健康熔断仍归 health 域，A2-04 §6）

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.platform_code.strip():
            raise AccountInvalid("Account 需要非空 id 与 platform")
        if not self.account_name.strip():
            raise AccountInvalid("Account 需要非空 account_name")
        if self.id != account_identity(self.platform_code, self.account_code):
            # 存量行/适配器只带 id 时，从规范 id 反推 account_code（多账号兼容）：
            # 形状不对就显式拒绝，绝不静默改号。
            prefix = f"{self.platform_code.strip()}:"
            suffix = self.id[len(prefix):] if self.id.startswith(prefix) else ""
            if not suffix or ":" in suffix:
                raise AccountInvalid(
                    f"Account id {self.id!r} 与 (platform, account_code) 编址不一致"
                )
            object.__setattr__(self, "account_code", suffix)
        for cred in self.credentials:
            if cred.account_id != self.id:
                raise AccountInvalid("凭据必须绑定本账户，禁止按应用共享")

    @property
    def identity(self) -> tuple[str, str]:
        return (self.platform_code, self.account_code)


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


def vault_ref(account_id: str, kind: str) -> str:
    """保险库引用 = (account_id, kind) 的规范串。"""

    if not account_id.strip() or kind.strip() == "":
        raise DomainError("vault ref 需要非空的 account_id 与 kind")
    return f"{account_id}:{kind}"


@dataclass(frozen=True)
class CredentialHealth:
    """vault.health() 出品：喂给健康域与"待处理"列表（A4-01 §1）。

    revoked_at 非空 = 本地副本已撤销（凭据不可用、等待重新停靠）；
    客户端自己的登录态不受影响（ADR-016）。
    """

    account_id: str
    kind: str
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
    ) -> "CredentialHealth":
        """分级谓词在 shared 内核单源重算——适配器只交数据。"""

        return cls(
            account_id=account_id,
            kind=kind,
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
    account_code: str = DEFAULT_ACCOUNT_CODE
    credentials: tuple[Credential, ...] = field(default_factory=tuple)
