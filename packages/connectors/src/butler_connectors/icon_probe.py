"""平台册 icon 探针表（2026-11-19）：按 conn_id 分流到各家的安装位置口径。

与 `version_probe` 同构：声明式连接器没有 adapter 实例，这里给每个平台指定
DisplayName 前缀与 DisplayIcon 文件名兜底；未登记 = 不适用/未知（""）。
探测只读、不拉起客户端；读不到如实返回 ""（前端回落身份色点，不造假）。
"""

from __future__ import annotations

from collections.abc import Callable

from butler_connectors import app_icon

_ICONS: dict[str, Callable[[], str]] = {
    "doubao_cn": lambda: app_icon.platform_icon(
        prefixes=("doubao", "豆包"), exe_names=("Doubao.exe",)
    ),
    "qoder_cn": lambda: app_icon.platform_icon(
        prefixes=("qoder",), exe_names=("Qoder.exe",)
    ),
    "trae_cn": lambda: app_icon.platform_icon(
        prefixes=("trae",), exe_names=("Trae CN.exe", "Trae.exe")
    ),
    "workbuddy_cn": lambda: app_icon.platform_icon(
        prefixes=("workbuddy",), exe_names=("WorkBuddy.exe", "WorkBuddyAI.exe")
    ),
}


def platform_icon(conn_id: str) -> str:
    """conn_id → 本机客户端图标 data URI；未登记/取不到返回 ""。

    探测异常不在本层吞（红线 5）：组合根的 `_read_client_icon` 统一兜底成 ""
    （图标缺失不是故障，只是没有图标）。
    """
    probe = _ICONS.get(conn_id)
    return probe() or "" if probe is not None else ""
