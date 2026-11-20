"""手建接入源用例（ADR-033 裁决 4）。

用户接入源 = relay / local / api 型上游，不依赖本机客户端连接器：
- 编码即锚点，创建后不改；
- 必须有 base_url + protocol（PlatformEntry 域内校验）；
- origin=user，启动同步的 deprecate_missing 不会把它标退役。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from butler_core.platforms.domain import (
    PlatformAlreadyExists,
    PlatformEntry,
    PlatformInvalid,
)
from butler_core.platforms.ports import PlatformRepository
from butler_core.shared.time import now_utc

#: 接入源编码：小写字母/数字开头，允许 -/_，2–32 位（进 account_id，禁冒号）
_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


@dataclass
class CreatePlatform:
    platforms: PlatformRepository

    def execute(
        self,
        platform_code: str,
        platform_name: str,
        *,
        kind: str,
        base_url: str,
        protocol: str,
        models: tuple[str, ...] = (),
        credential_kinds: tuple[str, ...] = (),
    ) -> PlatformEntry:
        code = platform_code.strip().lower()
        if not _CODE_PATTERN.match(code):
            raise PlatformInvalid(
                f"接入源编码 {code!r} 非法（小写字母/数字开头，允许 -/_，2–32 位）"
            )
        if self.platforms.get(code) is not None:
            raise PlatformAlreadyExists(f"接入源编码已存在：{code}（编码是锚点，不覆盖）")
        entry = PlatformEntry(
            platform_code=code,
            platform_name=platform_name.strip(),
            created_at=now_utc(),
            platform_kind=kind.strip(),
            base_url=base_url.strip(),
            protocol=protocol.strip(),
            models=tuple(m.strip() for m in models),
            credential_kinds=tuple(k.strip() for k in credential_kinds if k.strip()),
            origin="user",
            capabilities=(),  # 无连接器 = 不产生 claim/health 动作
            schedule_times=(),  # 接入源不排班（调度属连接器平台）
        )
        self.platforms.upsert(entry)
        return entry
