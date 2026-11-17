"""平台域（A2-09，ADR-022）：连接器平台事实——第六业务域。

平台与账户/执行/调度都有关联（账户挂 platform_code、调度按平台排班、
执行按平台路由端口），独立成域避免寄居账户域造成引用倒挂；
域之间不互依（A1-05 §2 依赖恒等式），其它域只持 platform_code 字符串引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from butler_core.shared.errors import DomainError


class PlatformInvalid(DomainError):
    """平台事实形状非法——显式拒绝（红线 5）。"""


@dataclass(frozen=True)
class PlatformEntry:
    """平台册行（A2-09，ADR-021）：连接器平台事实的落库投影。

    DB 为真相源：启动时由组合根从 manifest upsert（SyncPlatforms），manifest
    里消失的平台落 deprecated 标记不删行（审计可溯）；is_active 是用户侧
    开关（停用平台不再出现在名册与一键导入）。"""

    platform_code: str
    platform_name: str
    created_at: datetime
    client_version: str = ""  # 本机客户端版本（同步时探测；"" = 探不到=未知，不猜）
    capabilities: tuple[str, ...] = ()  # ActionKind.value 列表（core 词表）
    credential_kinds: tuple[str, ...] = ()
    schedule_times: tuple[str, ...] = ()  # HH:MM 触发时间并集
    is_active: bool = True
    deprecated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.platform_code.strip():
            raise PlatformInvalid("PlatformEntry 需要非空 platform_code")
        if not self.platform_name.strip():
            raise PlatformInvalid("PlatformEntry 需要非空 platform_name")
