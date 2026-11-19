"""本机已安装客户端版本探测：平台册 client_version 的通用事实源。

两端口径（与 doubao_cn/localenv、qoder_runtime 同族，不另造第三种）：

- Windows：卸载注册表项的 ``DisplayVersion``。多版本并存（本机 WorkBuddy 5.11.3 与
  WorkBuddy AI 5.9.4、Qoder 双域）时取版本最大者——"这台机器装的最新客户端是几"，
  与 ``qoder_runtime.installed_version`` 的"取最新版本目录"同口径。
- macOS：``.app/Contents/Info.plist`` 的 ``CFBundleShortVersionString``。

一律只读、不拉起客户端；未安装/读不到返回 ``""``（名册如实显示未知，不猜，
红线 5）。匹配优先用 DisplayName 前缀，其次用 DisplayIcon 的 exe 文件名，
避免同族产品（WorkBuddy 与 WorkBuddy AI）互相当成对方。
"""

from __future__ import annotations

import os
import plistlib
import sys
from collections.abc import Iterable
from pathlib import Path

_MAC_BASES = ("/Applications", "~/Applications")


def display_version(
    *,
    prefixes: tuple[str, ...],
    app_names: tuple[str, ...] = (),
    exe_names: tuple[str, ...] = (),
) -> str:
    """本机最新已安装版本；platform 分流（非 win32 且非 darwin = ""）。

    ``prefixes`` 走 DisplayName 前缀（casefold）；``exe_names`` 走 DisplayIcon
    文件名兜底（DisplayName 被本地化/改名时的第二道匹配）。
    """
    if sys.platform == "darwin":
        return _max_version(_mac_versions(app_names))
    if sys.platform != "win32":
        return ""
    return _max_version(_windows_versions(prefixes, exe_names))


def _max_version(versions: Iterable[str]) -> str:
    """取版本最大者；全空 = ""（多装并存时以最新为准）。"""
    items = [v.strip() for v in versions if v and v.strip()]
    if not items:
        return ""
    return max(items, key=_version_key)


def _version_key(version: str) -> tuple[int, ...]:
    """``5.11.3`` → (5, 11, 3)：非数字段按 0，长度不齐时短者补 0 由 max 天然处理。"""
    parts: list[int] = []
    for segment in version.replace("-", ".").split("."):
        digits = "".join(ch for ch in segment if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _windows_versions(prefixes: tuple[str, ...], exe_names: tuple[str, ...]) -> list[str]:
    """三处卸载注册表里的命中版本（HKCU / HKLM / WOW6432Node）。"""
    if sys.platform != "win32":
        return []  # 非 Windows 不 import winreg（平台专用）
    rows = _registry_rows()
    found: list[str] = []
    for values in rows:
        display = values.get("DisplayName", "").casefold()
        icon = Path(values.get("DisplayIcon", "").split(",")[0].strip().strip('"')).name.casefold()
        matched = any(display.startswith(p.casefold()) for p in prefixes)
        if not matched and icon:
            matched = any(icon == e.casefold() for e in exe_names)
        version = values.get("DisplayVersion", "").strip()
        if matched and version:
            found.append(version)
    return found


def _registry_rows() -> list[dict[str, str]]:
    """卸载注册表项的值表（逐条逐值容错；hive 缺失跳过不中断）。"""
    import winreg

    hives = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
    )
    out: list[dict[str, str]] = []
    for hive, path in hives:
        try:
            root = winreg.OpenKey(hive, path, 0, winreg.KEY_READ)
        except OSError:
            continue  # hive 不存在/无权限：换下一处
        with root:
            index = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    sub = winreg.OpenKey(root, sub_name, 0, winreg.KEY_READ)
                except OSError:
                    continue
                with sub:
                    values: dict[str, str] = {}
                    for field in ("DisplayName", "DisplayVersion", "DisplayIcon"):
                        try:
                            values[field] = str(winreg.QueryValueEx(sub, field)[0]).strip()
                        except OSError:
                            continue  # 单值缺失不丢整条
                if values:
                    out.append(values)
    return out


def _mac_versions(app_names: tuple[str, ...]) -> list[str]:
    """各 .app 的 CFBundleShortVersionString（plistlib 纯标准库）。"""
    found: list[str] = []
    for base in _MAC_BASES:
        root = Path(os.path.expanduser(base))
        for name in app_names:
            plist = root.joinpath(name, "Contents", "Info.plist")
            try:
                with open(plist, "rb") as fh:
                    data = plistlib.load(fh)
            except (OSError, plistlib.InvalidFileException):
                continue  # 未安装/非 plist：换下一个根 × 形态
            version = data.get("CFBundleShortVersionString") if isinstance(data, dict) else None
            if version:
                found.append(str(version))
    return found
