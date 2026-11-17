"""通知中心（A4-01 §3）：Event 的唯一消费者出口——其他订阅者不许直接通知。

- 渠道可插拔，按 min_severity 阈值投递：silent < badge < push
- 默认渠道：应用内（badge 起）；系统通知（push 起，桌面托盘后续接入）、
  Webhook / 邮件按 A4-01 §3 默认关闭，需要时实现对应渠道类挂进来即可
- 用户按事件类型覆盖级别的设置项在 M0 之后引入（severity map 注入点预留）
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from butler_core.shared.events import Event, Severity

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

    name = "in-platform"
    min_severity = Severity.BADGE

    def __init__(self) -> None:
        self.items: list[Event] = []

    def deliver(self, event: Event) -> None:
        self.items.append(event)


#: 通知正文（A4-01 §3）：只复述事件事实与下一步，不做层级→文案的语义映射。
def _notification_text(event: Event) -> tuple[str, str]:
    level = str(event.payload.get("level") or "")
    who = event.account_id or "账户"
    if event.type.value == "ACCOUNT_HEALTH_CHANGED":
        body = f"{who}：健康级别变为 {level}，请打开管家待办处理（重新登录 / 重新扫描）。"
    else:
        body = f"{who}：{event.type.value}" + (f"（{level}）" if level else "") + "，请打开管家查看。"
    return "Butler · 需要你处理", body


def _applescript_string(text: str) -> str:
    """AppleScript 双引号字面量转义（通知正文可能含中文引号/反斜杠）。"""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _platform_notify(title: str, body: str) -> None:
    """系统通知真实投递：macOS osascript / Linux notify-send；其余平台如实失败。"""
    if sys.platform == "darwin":
        subprocess.run(
            [
                "osascript",
                "-e",
                f"display notification {_applescript_string(body)} "
                f"with title {_applescript_string(title)}",
            ],
            check=True,
            timeout=5,
        )
        return
    if sys.platform.startswith("linux") and shutil.which("notify-send"):
        subprocess.run(["notify-send", title, body], check=True, timeout=5)
        return
    raise RuntimeError(
        f"系统通知渠道未支持平台 {sys.platform}（如实失败，不假装送达）"
    )


class SystemChannel(NotificationChannel):
    """桌面系统通知（A4-01 §3 push 渠道；ADR-015）。

    runner 可注入（测试不真弹通知）；投递失败由 NotificationCenter 隔离并记日志，
    不影响业务主流程。Windows 端暂由平台函数如实抛错，桌面壳接入时替换 runner。
    """

    name = "system"
    min_severity = Severity.PUSH

    def __init__(self, runner: Callable[[str, str], Any] | None = None) -> None:
        self._runner = runner or _platform_notify

    def deliver(self, event: Event) -> None:
        title, body = _notification_text(event)
        self._runner(title, body)


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
