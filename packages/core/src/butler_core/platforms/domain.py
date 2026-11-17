"""平台域（A2-09，ADR-022）：连接器平台事实——第六业务域。

平台与账户/执行/调度都有关联（账户挂 platform_code、调度按平台排班、
执行按平台路由端口），独立成域避免寄居账户域造成引用倒挂；
域之间不互依（A1-05 §2 依赖恒等式），其它域只持 platform_code 字符串引用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from butler_core.shared.errors import DomainError


class PlatformInvalid(DomainError):
    """平台事实形状非法——显式拒绝（红线 5）。"""


#: 平台类型词表（2026-11-18 裁决）：web=网页版 / client=本机客户端。
#: "" 仅老库历史行/未申报兼容，新申报必须显式二选一（manifest 侧必填）。
PLATFORM_KINDS = ("web", "client")

#: 调度时间格式（分钟粒度）
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass(frozen=True)
class PlatformEntry:
    """平台册行（A2-09，ADR-021）：连接器平台事实的落库投影。

    DB 为真相源：启动时由组合根从 manifest upsert（SyncPlatforms），manifest
    里消失的平台落 deprecated 标记不删行（审计可溯）；is_active 是用户侧
    开关（停用平台不再出现在名册与一键导入）。"""

    platform_code: str
    platform_name: str  # manifest 事实名（连接器申报）
    created_at: datetime
    platform_kind: str = ""  # web=网页版 / client=本机客户端（PLATFORM_KINDS；"" = 历史行未申报）
    client_version: str = ""  # 本机客户端版本（同步时探测；"" = 探不到=未知，不猜）
    capabilities: tuple[str, ...] = ()  # ActionKind.value 列表（core 词表）
    credential_kinds: tuple[str, ...] = ()
    schedule_times: tuple[str, ...] = ()  # HH:MM 触发时间并集（manifest 缺省）
    #: 用户覆盖的调度执行时间（None = 跟随 manifest；空元组 = 该平台不排班，
    #: 2026-11-18 裁决：调度时间可由平台管理页直接编辑）
    schedule_override: tuple[str, ...] | None = None
    #: 用户改的显示名（"" = 跟随 manifest 名；2026-11-18 裁决：平台信息可编辑）
    name_override: str = ""
    is_active: bool = True
    deprecated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.platform_code.strip():
            raise PlatformInvalid("PlatformEntry 需要非空 platform_code")
        if not self.platform_name.strip():
            raise PlatformInvalid("PlatformEntry 需要非空 platform_name")
        if self.name_override.strip() != "" and len(self.name_override) > 40:
            raise PlatformInvalid("PlatformEntry name_override 过长（≤40）")
        if self.schedule_override is not None:
            for slot in self.schedule_override:
                if not _HHMM.match(slot):
                    raise PlatformInvalid(
                        f"PlatformEntry schedule_override 里 {slot!r} 不是 HH:MM"
                    )
        if self.platform_kind and self.platform_kind not in PLATFORM_KINDS:
            raise PlatformInvalid(
                f"PlatformEntry platform_kind={self.platform_kind!r} 不在词表 {PLATFORM_KINDS}"
            )
