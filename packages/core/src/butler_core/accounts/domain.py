"""账户域（A2-04）：Provider / Account 集合 / 凭据事实。

多账号（ADR-010）：一 Provider 挂 N 个 Account，身份 = (provider, account_key)；
凭据/权益/会话全部挂 account_id。凭据明文载体 Secret 与保险库引用也在本域
——健康分级枚举来自 shared 内核，域之间不互依（A1-05 §2 依赖恒等式）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from butler_core.shared.errors import DomainError
from butler_core.shared.health_level import HealthLevel, credential_level
from butler_core.shared.time import now_utc

DEFAULT_ACCOUNT_KEY = "main"
EXPIRING_WINDOW_DAYS = 3  # CREDENTIAL_EXPIRING 预警窗（旧值不变，A2-07 §2）


class AccountInvalid(DomainError):
    """账户身份或凭据形状非法——显式拒绝（红线 5）。"""


class AccountAlreadyExists(AccountInvalid):
    """(provider, account_key) 已存在且事实冲突——不静默改号。"""


class EmptySecret(DomainError):
    """空明文入库 = 拒绝执行（红线 5）。"""


def account_identity(provider: str, account_key: str = DEFAULT_ACCOUNT_KEY) -> str:
    """账户规范 id：``{provider}:{account_key}``——全库唯一锚点单源。"""

    if not provider.strip():
        raise AccountInvalid("provider（connector id）不能为空")
    if not account_key.strip() or ":" in account_key:
        raise AccountInvalid("account_key 非空且不含冒号")
    return f"{provider.strip()}:{account_key.strip()}"


def main_account_id(provider: str) -> str:
    """兼容名：首账号（main）的规范 id——与存量 `:main` 编址零迁移兼容。"""

    return account_identity(provider, DEFAULT_ACCOUNT_KEY)


@dataclass(frozen=True)
class Provider:
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


@dataclass(frozen=True)
class Session:
    """本机会话：存储位置 + 可迁移级别。"""

    account_id: str
    location: str
    level: str = "local"  # local | inject | server


@dataclass(frozen=True)
class Account:
    """账户聚合根（集合语义）：Run / Event / Sample / 凭据全挂 account_id。"""

    id: str
    provider: str
    display_name: str
    created_at: datetime
    account_key: str = DEFAULT_ACCOUNT_KEY
    credentials: tuple[Credential, ...] = ()
    entitlement: Entitlement | None = None
    sessions: tuple[Session, ...] = ()
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.provider.strip():
            raise AccountInvalid("Account 需要非空 id 与 provider")
        if not self.display_name.strip():
            raise AccountInvalid("Account 需要非空 display_name")
        if self.id != account_identity(self.provider, self.account_key):
            # 存量行/适配器只带 id 时，从规范 id 反推 account_key（多账号兼容）：
            # 形状不对就显式拒绝，绝不静默改号。
            prefix = f"{self.provider.strip()}:"
            suffix = self.id[len(prefix):] if self.id.startswith(prefix) else ""
            if not suffix or ":" in suffix:
                raise AccountInvalid(
                    f"Account id {self.id!r} 与 (provider, account_key) 编址不一致"
                )
            object.__setattr__(self, "account_key", suffix)
        for cred in self.credentials:
            if cred.account_id != self.id:
                raise AccountInvalid("凭据必须绑定本账户，禁止按应用共享")

    @property
    def identity(self) -> tuple[str, str]:
        return (self.provider, self.account_key)


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
    """vault.health() 出品：喂给健康域与"待处理"列表（A4-01 §1）。"""

    account_id: str
    kind: str
    expires_at: datetime | None = None
    level: HealthLevel = HealthLevel.HEALTHY

    @classmethod
    def build(
        cls,
        *,
        account_id: str,
        kind: str,
        expires_at: datetime | None,
        clock: Callable[[], datetime] = now_utc,
        warn_window_days: int = EXPIRING_WINDOW_DAYS,
    ) -> "CredentialHealth":
        """分级谓词在 shared 内核单源重算——适配器只交数据。"""

        return cls(
            account_id=account_id,
            kind=kind,
            expires_at=expires_at,
            level=credential_level(expires_at, clock(), warn_window_days=warn_window_days),
        )


@dataclass(frozen=True)
class AccountDraft:
    """注册用例的入参形状（避免在用例签名里堆参数）。"""

    provider: str
    display_name: str
    account_key: str = DEFAULT_ACCOUNT_KEY
    credentials: tuple[Credential, ...] = field(default_factory=tuple)
