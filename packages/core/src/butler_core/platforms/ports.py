"""平台域端口（A2-09）：平台册的持久化契约（ADR-021/022）。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from butler_core.platforms.domain import PlatformEntry


class PlatformRepository(ABC):
    """平台册端口：连接器平台事实的持久化（DB 为真相源）。

    sync = manifest 事实 upsert + 缺失平台落 deprecated（不删行，审计可溯）。"""

    @abstractmethod
    def upsert(self, entry: PlatformEntry) -> None: ...

    @abstractmethod
    def deprecate_missing(self, platform_codes: frozenset[str]) -> list[str]:
        """把不在 platform_codes 里的平台落 deprecated_at（幂等）；返回本次新标记的 code。"""

    @abstractmethod
    def set_schedule_override(
        self, platform_code: str, times: tuple[str, ...] | None
    ) -> PlatformEntry | None:
        """写调度覆盖（None = 恢复跟随 manifest）；返回更新后的行（平台不存在 = None）。"""

    @abstractmethod
    def get(self, platform_code: str) -> PlatformEntry | None: ...

    @abstractmethod
    def list_all(self) -> list[PlatformEntry]: ...
