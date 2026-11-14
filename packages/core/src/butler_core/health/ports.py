"""健康域端口（A2-07 §3）：探针 / 评级记忆 / 凭据事实来源。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Protocol

from butler_core.health.domain import HealthLevel


class HealthStateStore(ABC):
    """健康扫描记忆：变更才产事件（防每日重发）。"""

    @abstractmethod
    def get_credential_notified_level(self, account_id: str, kind: str) -> str | None: ...

    @abstractmethod
    def set_credential_notified_level(
        self, account_id: str, kind: str, level: HealthLevel
    ) -> None: ...

    @abstractmethod
    def get_account_level(self, account_id: str) -> HealthLevel | None: ...

    @abstractmethod
    def set_account_level(self, account_id: str, level: HealthLevel) -> None: ...


class _CredentialFact(Protocol):
    account_id: str
    kind: str
    expires_at: datetime | None


class CredentialSource(Protocol):
    """vault.health() 的结构化视图——避免健康域反向依赖账户域实现。"""

    def health(self) -> list[_CredentialFact]: ...


class HealthProbePort(Protocol):
    """连接器侧探针：如实上报原始结果，不做语义决策。"""

    def probe(self, account_id: str) -> str: ...
