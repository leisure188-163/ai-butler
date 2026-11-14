"""健康域（A2-07）：健康分级与风险规则。

五级枚举与凭据分级谓词是跨域公共值对象，实体定义在 shared.health_level
（accounts 域的 CredentialHealth 也需要它），本模块是健康域的正式出口。
"""

from __future__ import annotations

from butler_core.shared.health_level import (
    RISK_NO_AUTH_STREAK,
    AccountHealth,
    HealthLevel,
    account_repair_hint,
    credential_level,
    worst_level,
)

__all__ = [
    "RISK_NO_AUTH_STREAK",
    "AccountHealth",
    "HealthLevel",
    "account_repair_hint",
    "credential_level",
    "worst_level",
]
