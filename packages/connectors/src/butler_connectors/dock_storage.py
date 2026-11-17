"""存储信封组装（DPAPI/mac）：从 dockio 拆出的纯编解码层。

不放扫描/注册策略——``dockio.scan_storage`` 决定目录与 profile；
本模块只负责把磁盘字节与 Local State 包成 self-contained envelope。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path


def glob_dirs(base: Path) -> list[Path]:
    """候选末段含通配 = 目录 glob（按名排序稳定）；否则视为目录本身。"""
    if "*" in str(base) or "?" in str(base):
        return sorted(p for p in base.parent.glob(base.name) if p.is_dir())
    return [base] if base.is_dir() else []


def dpapi_envelope(dat: Path, state: Path) -> str:
    """组自包含信封：base64(JSON{dat: b64(文件字节), key_b64: Local State 原文})。"""
    try:
        state_data = json.loads(state.read_text(encoding="utf-8"))
        key_b64 = state_data["os_crypt"]["encrypted_key"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Local State 形状不符: {exc}") from exc
    if not isinstance(key_b64, str) or not key_b64:
        raise ValueError("Local State 缺 os_crypt.encrypted_key")
    payload = {
        "dat": base64.b64encode(dat.read_bytes()).decode("ascii"),
        "key_b64": key_b64,
    }
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def mac_envelope(dat: Path) -> str:
    """mac 信封：base64(JSON{dat})——钥匙不进信封（Keychain 现取，密钥绝不入 vault）。"""
    payload = {"dat": base64.b64encode(dat.read_bytes()).decode("ascii")}
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
