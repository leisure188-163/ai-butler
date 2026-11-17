"""账户域端口（A2-04 §3）：端口随域走，废止全库单一 ports.py。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from butler_core.accounts.domain import Account, CredentialHealth, Secret, SessionSighting
from butler_core.shared.errors import DomainError


class CredentialMissing(DomainError):
    """vault.load 缺凭据 kind 的端口语义错误。"""


class CredentialRevoked(CredentialMissing):
    """凭据已被主动撤销（本地副本清空，等待重新停靠）——仍是"缺凭据"语义。"""


class AccountRepository(ABC):
    """账户名册端口：集合语义（按 platform 列多账号）。"""

    @abstractmethod
    def save(self, account: Account) -> None: ...

    @abstractmethod
    def get(self, account_id: str) -> Account | None: ...

    @abstractmethod
    def list_by_platform(self, platform: str) -> list[Account]: ...

    @abstractmethod
    def list_all(self) -> list[Account]: ...


class VaultPort(ABC):
    """凭据保险库端口：明文只在适配器侧，core 只认这套 API。"""

    @abstractmethod
    def store(
        self,
        account_id: str,
        kind: str,
        secret: Secret,
        *,
        expires_at: datetime | None = None,
    ) -> None: ...

    @abstractmethod
    def load(self, account_id: str, kinds: list[str]) -> list[Secret]: ...

    @abstractmethod
    def rotate(
        self,
        account_id: str,
        kind: str,
        new_secret: Secret,
        *,
        expires_at: datetime | None = None,
    ) -> None: ...

    @abstractmethod
    def revoke(self, account_id: str, *, reason: str) -> int:
        """撤销该账户全部本地凭据副本：归档旧值、删主引用、标记 revoked。

        只动 butler 自己的库，不触碰客户端会话；返回本次新撤销的条目数
        （已撤销条目幂等跳过）。重新 store 同 (account_id, kind) 会清掉标记。
        """

    @abstractmethod
    def health(self) -> list[CredentialHealth]: ...


class CredentialPool(Protocol):
    """凭据池端口（ADR-012 裁决 3）：现用现取 + 短 TTL 缓存，读取全审计。

    网关反代热路径取凭据的唯一入口；实现必须让任何 acquire（含缓存命中）
    都有审计留痕（plans/02 §0 红线级）。缺凭据显式抛（承 VaultPort.load
    语义，不静默给空）。"""

    def acquire(self, account_id: str, kind: str) -> Secret:
        """取一个最小授权凭据（一次只解密申报的一个 kind）。"""
        ...

    def invalidate(self, account_id: str, kind: str) -> None:
        """失效指定缓存项（凭据轮换/健康降级时由调用方触发）。"""
        ...


class SessionSourcePort(Protocol):
    """本机会话/凭据扫描：多 profile 枚举（ADR-003 §3）+ 会话观测（R5-S1）。"""

    def enumerate_accounts(self, platform: str) -> Iterable[tuple[str, str]]:
        """产出 (account_code, account_name)；不可得通道如实返回空。"""
        ...

    def scan_sessions(self, platform: str) -> Iterable[SessionSighting]:
        """只读枚举本机会话位置（R5-S1，ADR-013 裁决 1：首批 workspace）。

        适配器契约：看形状即止，禁写动作；客户端运行中持锁等读不了的情况
        如实跳过（不上报猜测的形状）；账户绑定不可得时 device_ref=None。"""
        ...
