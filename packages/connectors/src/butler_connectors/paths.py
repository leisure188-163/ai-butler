"""连接器包根定位 + 平台宏路径展开（storage/Credential 扫描的机械部分）。

- 包根 = 已安装包 ``butler_connectors`` 的目录：连接器数据文件
  （manifest.yaml / declarative/*.yaml）随包分发（hatch wheel 已含）
- 平台宏：``%APPDATA%`` / ``%LOCALAPPDATA%`` / ``~``——显式解析为什么都
  认识，遇到陌生宏直接爆，不做静默跳过（红线 5）
"""

from __future__ import annotations

import importlib.resources
import os
import re
from pathlib import Path

_MACRO_RE = re.compile(r"%([A-Z_]+)%")


def package_root(conn_id: str = "") -> Path:
    """连接器子包目录（如 .../butler_connectors/trae_cn）。"""
    base = Path(str(importlib.resources.files("butler_connectors")))
    return base / conn_id if conn_id else base


def expand_storage_path(raw: str) -> Path | None:
    """展开平台宏 → 绝对路径；宏无法解析（如 mac 上没有 %APPDATA%）返回 None。

    返回 None = 该候选只是"不属于本平台"，属正常跳过；这不是静默兜底——
    扫描循环对"文件不存在"与"平台不适用"一视同仁地换下一个候选，
    全部落空才在 DockOutcome.issues 里如实上报。
    """

    def repl(match: re.Match[str]) -> str:
        value = os.environ.get(match.group(1))
        if value is None:
            raise _MacroMissing(match.group(0))
        return value  # 忘了这行 = 宏被替换成空串（真机 dock 扫描全落空的根因）

    try:
        text = _MACRO_RE.sub(repl, raw)
    except _MacroMissing:
        return None
    return Path(os.path.expanduser(text))


class _MacroMissing(Exception):
    pass


#: 自定义连接器目录（2026-11-18）：用户自建的声明式平台落在这里，
#: 与包内内置连接器同构（manifest.yaml + declarative/*.yaml），
#: 由 load_registry(custom_root=...) 一并装载。环境变量可改（测试/便携部署）。
_DEFAULT_CUSTOM_DIRNAME = "connectors"


def custom_connectors_root() -> Path:
    """自定义连接器根目录：``BUTLER_CUSTOM_CONNECTORS`` 优先，否则用户数据目录。"""
    override = os.environ.get("BUTLER_CUSTOM_CONNECTORS", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "butler" / _DEFAULT_CUSTOM_DIRNAME
    return Path.home() / ".butler" / _DEFAULT_CUSTOM_DIRNAME
