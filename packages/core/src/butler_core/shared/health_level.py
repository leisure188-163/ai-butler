"""账号健康模型（A4-01 §2）：五级分级 + 核心侧谓词与文案（端零映射）。

- 分级优先级：risk > expired > invalid > expiring > healthy
- risk 只在账号粒度出现（封号风险是账号信号）；凭据粒度只会是
  healthy / expiring / expired（credential_level）
- repair_hint 文案在 core 单源——UI 只渲染字符串，不做 level→文案映射（红线 2）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

RISK_NO_AUTH_STREAK = 3  # 连续 NO_AUTH → risk（2026-11-10 裁决）


class HealthLevel(StrEnum):
    """五级分级（A4-01 §2 §字面）。"""

    HEALTHY = "healthy"  # 静默
    EXPIRING = "expiring"  # 徽标提醒
    EXPIRED = "expired"  # 待处理 + repair_hint
    INVALID = "invalid"  # 待处理 + repair_hint
    RISK = "risk"  # push 通知

    @property
    def signal(self) -> str:
        """视觉信号桶（A3-01 §4）：ok / notice / attention / danger。

        UI 染色分类 core 单源——端不认识 level 字面量本身（端零映射）。
        """

        if self is HealthLevel.HEALTHY:
            return "ok"
        if self is HealthLevel.EXPIRING:
            return "notice"
        if self is HealthLevel.RISK:
            return "danger"
        return "attention"


_LEVEL_RANK = {
    HealthLevel.HEALTHY: 0,
    HealthLevel.EXPIRING: 1,
    HealthLevel.INVALID: 2,
    HealthLevel.EXPIRED: 3,
    HealthLevel.RISK: 4,
}


def worst_level(a: HealthLevel, b: HealthLevel) -> HealthLevel:
    """取更严重的一侧。"""
    return a if _LEVEL_RANK[a] >= _LEVEL_RANK[b] else b


def credential_level(
    expires_at: datetime | None, now: datetime, *, warn_window_days: int
) -> HealthLevel:
    """凭据粒度分级：只看有效期，不含 risk（账号信号）。"""
    if expires_at is None:
        return HealthLevel.HEALTHY  # 无期限 = 长期凭据，不因缺数据吓人
    if expires_at <= now:
        return HealthLevel.EXPIRED
    if expires_at <= now + timedelta(days=warn_window_days):
        return HealthLevel.EXPIRING
    return HealthLevel.HEALTHY


_REPAIR_HINTS = {
    HealthLevel.EXPIRED: "重新打开客户端登录",  # A4-01 §2 字面
    HealthLevel.INVALID: "打开登录页",
    HealthLevel.RISK: "连续鉴权失败，先人工验证账号是否受限",
    # expiring 只挂徽标；healthy 静默——都不带修复提示
}


def account_repair_hint(level: HealthLevel) -> str | None:
    """分级的建议动作文案：core 单源，UI 直渲染（端零映射）。"""
    return _REPAIR_HINTS.get(level)


@dataclass(frozen=True)
class AccountHealth:
    """A4-01 §2 字面：{level, evidence, checked_at}。port id 是补充。"""

    account_id: str
    level: HealthLevel
    evidence: tuple[str, ...] = ()
    repair_hint: str | None = None
    checked_at: datetime | None = None

    @classmethod
    def build(
        cls,
        *,
        account_id: str,
        level: HealthLevel,
        evidence: tuple[str, ...],
        checked_at: datetime,
    ) -> "AccountHealth":
        return cls(
            account_id=account_id,
            level=level,
            evidence=evidence,
            repair_hint=account_repair_hint(level),
            checked_at=checked_at,
        )
