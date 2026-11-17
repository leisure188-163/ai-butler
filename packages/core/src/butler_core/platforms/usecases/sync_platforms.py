"""平台域同步用例（A2-09，ADR-021/022）：manifest 事实 upsert + 缺失平台落 deprecated。

干净路径：facts 全量 upsert（UPSERT 保代理键不漂移）→ deprecate_missing 把
manifest 里消失的平台标记 deprecated_at（不删行，审计可溯）。
非法输入显式抛（PlatformEntry 自校验）；manifest 读取失败由组合根显式报错，
本用例不做静默兜底。
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.platforms.domain import PlatformEntry
from butler_core.platforms.ports import PlatformRepository


@dataclass
class SyncPlatforms:
    """平台册同步：facts = 本机全部连接器平台事实（manifest 投影，纯数据）。"""

    platforms: PlatformRepository

    def execute(self, facts: tuple[PlatformEntry, ...]) -> list[str]:
        """返回本次新落 deprecated 的 platform_code 列表（幂等重复运行为空）。"""
        for fact in facts:
            self.platforms.upsert(fact)
        return self.platforms.deprecate_missing(frozenset(f.platform_code for f in facts))
