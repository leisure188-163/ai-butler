"""调度域端口（A2-08 §3）：定时触发与窗口配置持久化。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from butler_core.scheduling.domain import Trigger


class SchedulerPort(ABC):
    """注册/取消定时触发（engine 侧实现）。"""

    @abstractmethod
    def register(self, trigger: Trigger, fire: Callable[[], None]) -> str: ...

    @abstractmethod
    def cancel(self, handle: str) -> None: ...


class TriggerRepoPort(ABC):
    @abstractmethod
    def save(self, trigger: Trigger) -> None: ...

    @abstractmethod
    def list_enabled(self) -> list[Trigger]: ...
