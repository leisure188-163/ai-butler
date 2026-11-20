"""编辑用户接入源（ADR-033 裁决 5）：只允许 origin=user 的行改连接事实。

连接器平台（origin=connector）的 base_url/protocol/models 由 manifest 申报，
本用例显式拒绝，避免用户改完被下一次同步覆盖。
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.platforms.domain import (
    PROTOCOLS,
    PlatformEntry,
    PlatformInvalid,
)
from butler_core.platforms.ports import PlatformRepository


@dataclass
class UpdateProvider:
    platforms: PlatformRepository

    def execute(
        self,
        platform_code: str,
        *,
        platform_name: str | None = None,
        is_active: bool | None = None,
        base_url: str | None = None,
        protocol: str | None = None,
        models: tuple[str, ...] | None = None,
        credential_kinds: tuple[str, ...] | None = None,
    ) -> PlatformEntry:
        entry = self.platforms.get(platform_code)
        if entry is None:
            raise PlatformInvalid(f"接入源不存在：{platform_code}")
        if entry.origin != "user":
            raise PlatformInvalid(
                f"{platform_code} 是连接器平台，连接事实由 manifest 申报，不能在此改写"
            )
        if platform_name is not None and not platform_name.strip():
            raise PlatformInvalid("platform_name 不能改为空")
        if base_url is not None:
            base_url = base_url.strip()
            if not base_url.startswith(("http://", "https://")):
                raise PlatformInvalid("base_url 必须以 http:// 或 https:// 开头")
        if protocol is not None and protocol.strip() not in PROTOCOLS:
            raise PlatformInvalid(f"protocol={protocol!r} 不在词表 {PROTOCOLS}")
        if models is not None and any(not m.strip() for m in models):
            raise PlatformInvalid("models 不能含空项")
        updated = self.platforms.update_profile(
            platform_code,
            platform_name=platform_name.strip() if platform_name is not None else None,
            is_active=is_active,
            base_url=base_url,
            protocol=protocol.strip() if protocol is not None else None,
            models=tuple(m.strip() for m in models) if models is not None else None,
            credential_kinds=(
                tuple(k.strip() for k in credential_kinds if k.strip())
                if credential_kinds is not None
                else None
            ),
        )
        if updated is None:
            raise PlatformInvalid(f"接入源不存在：{platform_code}")
        return updated
