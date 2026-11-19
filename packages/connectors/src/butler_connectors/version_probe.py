"""平台册 client_version 探针表（声明式连接器没有 adapter 实例，钩子按 conn_id 查表）。

`apps/server` 的 `sync_platform_facts` 调端口实例的 `read_client_version()`：
adapter 型连接器自己实现，声明式连接器经本表分流。未登记 = 不适用/未知（""）。
探测一律只读，不拉起客户端；读不到就如实返回 ""（名册显示未知，不造数据）。
"""

from __future__ import annotations

from collections.abc import Callable

from butler_connectors import qoder_runtime

_PROBES: dict[str, Callable[[], str]] = {
    # Qoder 空壳安装根 + .qoder-versions 多版本并存：探针取最新版本目录的 productVersion
    "qoder_cn": qoder_runtime.installed_version,
}


def client_version(conn_id: str) -> str:
    """conn_id → 本机客户端版本；未登记返回 ""（= 未知/不适用）。

    探测异常不在此吞（红线 5）：组合根的 `_read_client_version` 统一兜底成 "",
    这里只负责按 conn_id 分流与"取到空值即未知"的如实返回。
    """
    probe = _PROBES.get(conn_id)
    return probe() or "" if probe is not None else ""
