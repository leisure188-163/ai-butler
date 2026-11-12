"""通知中心（A4-01 §3）：Event 的唯一消费者出口——其他订阅者不许直接通知。

- 渠道可插拔，按 min_severity 阈值投递：silent < badge < push
- 默认渠道：应用内（badge 起）；系统通知（push 起，桌面托盘后续接入）、
  Webhook / 邮件按 A4-01 §3 默认关闭，需要时实现对应渠道类挂进来即可
- 用户按事件类型覆盖级别的设置项在 M0 之后引入（severity map 注入点预留）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from kabao_core.domain.event import Event, Severity

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {
    Severity.SILENT: 0,
    Severity.BADGE: 1,
    Severity.PUSH: 2,
}


class NotificationChannel(ABC):
    """通知渠道适配器：声明自己的最低投递级别。"""

    name: str = "channel"
    min_severity: Severity = Severity.BADGE

    @abstractmethod
    def deliver(self, event: Event) -> None: ...


class InAppChannel(NotificationChannel):
    """应用内：待处理列表 + 托盘角标。M0 内存收集；server API / 桌面托盘后续接。"""

    name = "in-app"
    min_severity = Severity.BADGE

    def __init__(self) -> None:
        self.items: list[Event] = []

    def deliver(self, event: Event) -> None:
        self.items.append(event)


class NotificationCenter:
    """订阅事件总线，按渠道阈值分发。渠道故障互相隔离、不影响主流程。"""

    def __init__(self, channels: list[NotificationChannel]) -> None:
        self._channels = list(channels)

    def on_event(self, event: Event) -> None:
        rank = _SEVERITY_RANK[event.severity]
        for channel in self._channels:
            if rank < _SEVERITY_RANK[channel.min_severity]:
                continue
            try:
                channel.deliver(event)
            except Exception:
                # 单渠道失败不拖垮其他渠道，也不影响业务主流程（A4-01 §5 语义）
                logger.exception("通知渠道 %s 投递失败（已隔离）", channel.name)
