"""凭据保险库领域模型（A4-01 §1）。

- Secret 是唯一合法的明文载体：repr/str 永远 [REDACTED]（A4-01 §1：
  日志/事件/台账一律脱敏，凭据明文只存在于内存与 Keychain）
- kind 是开放词汇表：由 Connector manifest 申报（A2-02 §1 "kinds: [ss_aes]"），
  core 不封枚举——新面对面接入不需要改 core
- 状态分级谓词在 core 单源（端零映射，红线 2）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from kabao_core.domain.errors import DomainError
from kabao_core.domain.health import HealthLevel, credential_level
from kabao_core.domain.run import now_utc

EXPIRING_WINDOW_DAYS = 3  # CREDENTIAL_EXPIRING 预警窗口默认值（2026-11-10 裁决）


def vault_ref(account_id: str, kind: str) -> str:
    """保险库引用 = (account_id, kind) 的规范串。适配器拿它做物主键。"""

    if not account_id.strip() or kind.strip() == "":
        raise DomainError("vault ref 需要非空的 account_id 与 kind")
    return f"{account_id}:{kind}"


class EmptySecret(DomainError):
    """空明文入库 = 拒绝执行（红线 5：显式报错不静默兜底）。"""


@dataclass(frozen=True)
class Secret:
    """字分钟文值：内存中唯一合法的明文载体，展示/日志路径永远打码。"""

    _value: str

    def __post_init__(self) -> None:
        if self._value == "":
            raise EmptySecret("Secret 明文不能为空——空值是配置事故，不静默")

    def expose(self) -> str:
        """唯一取用明文的出口：调用方承担"绝不落日志/落盘"的责任（A4-01 §1）。"""
        return self._value

    def __repr__(self) -> str:  # 全链路脱敏：repr 是最先泄密的地方
        return "[REDACTED]"

    def __str__(self) -> str:
        return "[REDACTED]"


@dataclass(frozen=True)
class CredentialHealth:
    """vault.health() 出品：喂给健康中心与"待处理"列表（A4-01 §1）。"""

    account_id: str
    kind: str
    expires_at: datetime | None = None
    level: HealthLevel = HealthLevel.HEALTHY  # 凭据粒度只会是健康/预警/过期

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
        """分级在 core 谓词里完成——适配器只交数据，不做语义判断（端零映射）。"""

        return cls(
            account_id=account_id,
            kind=kind,
            expires_at=expires_at,
            level=credential_level(expires_at, clock(), warn_window_days=warn_window_days),
        )
