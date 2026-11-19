"""平台移出名册用例（2026-11-19 用户裁决）：误导入 / 不再使用的平台可移出。

语义边界：只删「平台事实行」，**不动账户、台账、凭据**——账户仍留在账户域，
重新导入（`adopt`）时按 platform_code 自动归位；历史领取记录照旧可查。
自定义平台的删除走连接器目录删除（`DELETE /platforms/custom/{code}`），
本用例只负责名册事实行（内置平台）。
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.platforms.ports import PlatformRepository


@dataclass
class RemovePlatform:
    """移出名册：返回是否真的删了行（不存在 = False，端侧 404）。"""

    platforms: PlatformRepository

    def execute(self, platform_code: str) -> bool:
        return self.platforms.remove(platform_code)
