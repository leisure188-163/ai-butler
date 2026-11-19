"""平台域同步用例（A2-09，ADR-021/022）：manifest 事实 upsert + 缺失平台落 deprecated。

干净路径：facts 全量 upsert（UPSERT 保代理键不漂移）→ deprecate_missing 把
连接器里消失的平台标记 deprecated_at（不删行，审计可溯）。
**策略性跳过不算消失**：`known_codes` 给"连接器宇宙"（含本次不纳册的类型，
如网页版），缺失判定只针对连接器真的退役/删除（2026-11-19 用户裁决：
同步平台只纳本机客户端，网页版留给人工导入）。
非法输入显式抛（PlatformEntry 自校验）；manifest 读取失败由组合根显式报错，
本用例不做静默兜底。
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.platforms.domain import PlatformEntry
from butler_core.platforms.ports import PlatformRepository


@dataclass
class SyncPlatforms:
    """平台册同步：facts = 本次要纳册的连接器平台事实（manifest 投影，纯数据）。"""

    platforms: PlatformRepository

    def execute(
        self,
        facts: tuple[PlatformEntry, ...],
        *,
        known_codes: frozenset[str] | None = None,
    ) -> list[str]:
        """返回本次新落 deprecated 的 platform_code 列表（幂等重复运行为空）。

        known_codes：连接器宇宙（默认 = facts 的编码集合）。传了它时，
        只把「不在宇宙里」的行落 deprecated——本次被策略跳过（如网页版）
        但连接器仍在的行保持原状，不会被误判成退役。
        """
        for fact in facts:
            self.platforms.upsert(fact)
        universe = (
            frozenset(known_codes)
            if known_codes is not None
            else frozenset(f.platform_code for f in facts)
        )
        return self.platforms.deprecate_missing(universe)
