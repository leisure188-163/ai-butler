"""声明式路由表装载（ADR-012 裁决 5/6）：模型 → 账户池静态映射，网关只读。

- 模型与校验**单源在 core**（``butler_core.execution.gateway_routes``）——
  server 管理面写入与网关装载共用同一 from_dict，两端口径永不漂移（R4-G6）
- 本模块只剩文件装载职责：路由 = 数据（JSON 文件 / 将来 server 契约下发）；
  文件缺失 = 空表（合法初始态），文件非法 = 显式报错（拒启，红线 5）
- M1 启动时装载一次；规则变更后重启网关进程生效（server 契约响应已注明）
"""

from __future__ import annotations

import json
from pathlib import Path

from butler_core.execution.gateway_routes import RouteRule, RouteTable  # noqa: F401  # 再导出（既有消费方）

__all__ = ["RouteRule", "RouteTable", "load_routes"]


def load_routes(path: Path) -> RouteTable:
    """从 JSON 文件装载路由表；缺失 = 空表（合法初始态），非法 = 显式报错。"""
    if not path.exists():
        return RouteTable(rules=())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"路由配置文件解析失败: {path}——{exc}") from exc
    try:
        return RouteTable.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"路由配置文件校验失败: {path}——{exc}") from exc
