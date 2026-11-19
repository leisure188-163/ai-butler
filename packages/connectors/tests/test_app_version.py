"""app_version 通用探针：口径单源（Windows 卸载注册表 DisplayVersion / mac Info.plist）。

真机事实（2026-11-19，本机）：Trae CN 3.4.20；WorkBuddy 5.11.3 与 WorkBuddy AI 5.9.4 并存。
"""

from __future__ import annotations

import pytest

from butler_connectors import app_version


def test_版本比较按数字段逐位(monkeypatch) -> None:
    """5.11.3 > 5.9.4（字符串比较会判反），3.4.20 > 3.4.2。"""
    assert app_version._version_key("5.11.3") > app_version._version_key("5.9.4")
    assert app_version._version_key("3.4.20") > app_version._version_key("3.4.2")


def test_多版本并存取最新() -> None:
    assert app_version._max_version(["5.9.4", "5.11.3"]) == "5.11.3"
    assert app_version._max_version(["", "  "]) == ""


def test_windows_按_DisplayName_前缀命中并取最新(monkeypatch) -> None:
    rows = [
        {"DisplayName": "WorkBuddy 5.11.3", "DisplayVersion": "5.11.3"},
        {"DisplayName": "WorkBuddy AI 5.9.4", "DisplayVersion": "5.9.4"},
        {"DisplayName": "Visual Studio Code", "DisplayVersion": "1.99.0"},
    ]
    monkeypatch.setattr(app_version, "_registry_rows", lambda: rows)
    monkeypatch.setattr(app_version.sys, "platform", "win32")
    assert app_version.display_version(prefixes=("workbuddy",)) == "5.11.3"


def test_windows_DisplayName_本地化时用_exe_兜底(monkeypatch) -> None:
    """DisplayName 被改名成本地语言时，DisplayIcon 的 exe 名是第二道匹配。"""
    rows = [
        {"DisplayName": "Trae CN 中文版", "DisplayVersion": "3.4.20", "DisplayIcon": r'D:\x\Trae CN.exe,0'},
        {"DisplayName": "Other", "DisplayVersion": "1.0.0", "DisplayIcon": r"D:\y\other.exe,0"},
    ]
    monkeypatch.setattr(app_version, "_registry_rows", lambda: rows)
    monkeypatch.setattr(app_version.sys, "platform", "win32")
    assert app_version.display_version(prefixes=("trae",), exe_names=("Trae CN.exe",)) == "3.4.20"


def test_windows_无命中返回空(monkeypatch) -> None:
    monkeypatch.setattr(app_version, "_registry_rows", lambda: [])
    monkeypatch.setattr(app_version.sys, "platform", "win32")
    assert app_version.display_version(prefixes=("trae",)) == ""


def test_非_windows_非_mac_返回空(monkeypatch) -> None:
    monkeypatch.setattr(app_version.sys, "platform", "linux")
    assert app_version.display_version(prefixes=("trae",)) == ""


def test_mac_读_Info_plist(monkeypatch, tmp_path) -> None:
    import plistlib

    app_dir = tmp_path / "Trae CN.app" / "Contents"
    app_dir.mkdir(parents=True)
    with open(app_dir / "Info.plist", "wb") as fh:
        plistlib.dump({"CFBundleShortVersionString": "3.4.20"}, fh)

    monkeypatch.setattr(app_version, "_MAC_BASES", (str(tmp_path),))
    monkeypatch.setattr(app_version.sys, "platform", "darwin")
    assert app_version.display_version(prefixes=("trae",), app_names=("Trae CN.app",)) == "3.4.20"
