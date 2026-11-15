"""网关路由表 JSON 文件存储（R4-G6，ADR-012 裁决 6）：server 管、网关只读装载。

- 单一事实源 = 数据根 ``gateway-routes.json``（``BUTLER_GATEWAY_ROUTES_FILE``
  可整体覆盖，测试/便携模式）；校验单源在 core RouteTable.from_dict
- load：文件缺失 = 空表合法初始态（与网关启动装载同语义）；非法 = 显式
  ValueError（不静默当空表——坏配置必须被发现，不是被藏起来）
- save：整表替换 + 原子写（tmp + os.replace）——防半截文件被网关下次启动装载
  （声明式配置，无增量 PATCH；替换即真相）
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from butler_core.execution.gateway_routes import RouteTable
from butler_core.execution.ports import GatewayRoutesStore

ROUTES_FILE_NAME = "gateway-routes.json"


class FileGatewayRoutesStore(GatewayRoutesStore):
    """路由表 JSON 文件存储：整表读写，原子落盘。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """规则文件路径（观测面/文档用）。"""
        return self._path

    def load(self) -> RouteTable:
        if not self._path.exists():
            return RouteTable(rules=())
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"路由配置文件解析失败: {self._path}——{exc}") from exc
        try:
            return RouteTable.from_dict(data)
        except ValueError as exc:
            raise ValueError(f"路由配置文件校验失败: {self._path}——{exc}") from exc

    def save(self, table: RouteTable) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(table.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self._path)  # 同目录原子替换，无半截文件窗口
