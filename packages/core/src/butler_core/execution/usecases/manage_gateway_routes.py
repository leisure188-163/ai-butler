"""路由规则管理用例（R4-G6，ADR-012 裁决 6）：server 管理面写、网关只读装载。

- 干净路径：``replace(data)`` = RouteTable.from_dict 校验（非法显式 ValueError
  逐条中文报错，红线 5——非法配置绝不落盘让网关下次启动拒启）→ store.save
  原子落盘 → 返回保存后的表
- ``current()`` = store.load()；文件缺失 = 空表合法初始态（与网关装载同语义）
- 文件 IO 失败（OSError 等）= 主流程失败显式上抛不吞（配置写不进去不是台账
  可以让的侧效应——落盘失败还回「已保存」是撒谎）
- 网关生效时机：M1 网关启动时装载，规则变更后需重启网关进程（契约响应注明）
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.execution.gateway_routes import RouteTable
from butler_core.execution.ports import GatewayRoutesStore


@dataclass
class ManageGatewayRoutes:
    """路由规则整表管理：replace = 校验 + 原子落盘；current = 只读装载。"""

    store: GatewayRoutesStore

    def current(self) -> RouteTable:
        """当前路由表（缺失 = 空表合法初始态）。"""
        return self.store.load()

    def replace(self, data: dict) -> RouteTable:
        """整表替换（声明式配置）：先校验后落盘，非法显式 ValueError。"""
        table = RouteTable.from_dict(data)
        self.store.save(table)
        return table
