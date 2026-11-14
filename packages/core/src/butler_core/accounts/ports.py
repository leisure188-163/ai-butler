"""账户域端口（A2-04 §3）：端口随域走，废止全库单一 ports.py。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from butler_core.accounts.domain import Account, CredentialHealth, Secret
from butler_core.shared.errors import DomainError


class CredentialMissing(DomainError):
    """vault.load 缺凭据 kind 的端口语义错误。"""


class AccountRepository(ABC):
    """账户名册端口：集合语义（按 provider 列多账号）。"""

    @abstractmethod
    def save(self, account: Account) -> None: ...

    @abstractmethod
    def get(self, account_id: str) -> Account | None: ...

    @abstractmethod
    def list_by_provider(self, provider: str) -> list[Account]: ...

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
    def health(self) -> list[CredentialHealth]: ...


class SessionSourcePort(Protocol):
    """本机会话/凭据扫描：多 profile 枚举（ADR-003 §3）。"""

    def enumerate_accounts(self, provider: str) -> Iterable[tuple[str, str]]:
        """产出 (account_key, display_name)；不可得通道如实返回空。"""
        ...
