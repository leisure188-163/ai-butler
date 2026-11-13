"""doubao localenv 离线测试：环境变量覆盖 + 纯函数 + subprocess/winreg 打桩。"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from kabao_connectors.doubao_cn import localenv


def test_version_code_derivation():
    assert localenv.version_code("2.35.8") == 23508
    assert localenv.version_code("2.35") == 23500
    assert localenv.version_code(" 2.35.8 ") == 23508  # 容忍首尾空白
    assert localenv.version_code("abc") is None
    assert localenv.version_code("147.0.7727.149") is None  # 四段 Chromium 内核号，不是应用版本


def test_resolve_port_env_override(monkeypatch):
    monkeypatch.setenv("DOUBAO_CDP_PORT", "9223")
    assert localenv.real_env().resolve_port() == 9223
    monkeypatch.delenv("DOUBAO_CDP_PORT", raising=False)
    assert localenv.real_env().resolve_port() == 9222


def test_resolve_port_invalid_env_raises(monkeypatch):
    monkeypatch.setenv("DOUBAO_CDP_PORT", "not-a-port")
    with pytest.raises(ValueError):
        localenv.real_env().resolve_port()


def test_read_version_env_override_wins(monkeypatch):
    monkeypatch.setenv("DOUBAO_VERSION", "9.9.9")
    assert localenv.real_env().read_version() == "9.9.9"


def test_locate_exe_env_override(monkeypatch, tmp_path):
    exe = tmp_path / "Doubao.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("DOUBAO_EXE", str(exe))
    assert localenv.real_env().locate_exe() == exe
    monkeypatch.setenv("DOUBAO_EXE", str(tmp_path / "missing.exe"))
    assert localenv.real_env().locate_exe() is None  # 覆盖路径不存在 = 未定位，不猜


@pytest.mark.skipif(sys.platform != "win32", reason="tasklist 进程扫描仅 Windows")
def test_process_pids_parses_tasklist(monkeypatch):
    rows = '"Doubao.exe","123","Console","1","1,000 K"\r\n"other.exe","5","Console","1","1 K"\r\n'
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout=rows.encode("utf-8"))

    monkeypatch.setattr(localenv.subprocess, "run", fake_run)
    assert localenv.real_env().process_pids() == [123]
    assert "tasklist" in recorded["cmd"][0]


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill 仅 Windows（mac 走 SIGKILL 分支）")
def test_kill_pid_uses_taskkill(monkeypatch):
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(localenv.subprocess, "run", fake_run)
    localenv.real_env().kill_pid(123)
    assert recorded["cmd"][:3] == ["taskkill", "/F", "/T"]


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill 仅 Windows（mac 走 SIGKILL 分支）")
def test_kill_pid_process_gone_is_success(monkeypatch):
    """exit=128 = 没有找到进程（真机 2026-11-13：探得与击杀间隙退出）——
    杀净语义已达成，不报错（与 mac 分支 ProcessLookupError 宽容同事实）。"""
    monkeypatch.setattr(
        localenv.subprocess, "run",
        lambda cmd, **k: types.SimpleNamespace(returncode=128, stdout=b"", stderr=b""),
    )
    localenv.real_env().kill_pid(123)  # 不抛即过


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill 仅 Windows（mac 走 SIGKILL 分支）")
def test_kill_pid_failure_raises(monkeypatch):
    """真失败（如 5 = 拒绝访问）照旧显式抛——宽容只限「已不在」这一事实。"""
    monkeypatch.setattr(
        localenv.subprocess, "run",
        lambda cmd, **k: types.SimpleNamespace(returncode=5, stdout=b"", stderr=b"denied"),
    )
    with pytest.raises(RuntimeError, match="5"):
        localenv.real_env().kill_pid(123)


@pytest.mark.skipif(sys.platform != "win32", reason="detached 创建旗标仅 Windows")
def test_spawn_detached_passes_debug_port(monkeypatch):
    recorded = {}

    def fake_popen(cmd, **kwargs):
        recorded["cmd"] = list(cmd)
        recorded["kwargs"] = kwargs
        return types.SimpleNamespace(pid=1)

    monkeypatch.setattr(localenv.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("DOUBAO_CDP_PORT", "9223")
    exe = Path("D:/x/Doubao.exe")
    localenv.real_env().spawn_detached(exe)
    assert recorded["cmd"] == [str(exe), "--remote-debugging-port=9223"]
    assert "creationflags" in recorded["kwargs"]  # 脱离本进程生命周期


# --- mac .app 束分支（2026-11-12 真机取证：CDP 全链应答 / Info.plist 2.35.8）---


@pytest.fixture
def mac_app(tmp_path, monkeypatch):
    """假 .app 束 + darwin 平台面：Info.plist（plistlib 可读）与主程序。"""
    app = tmp_path / "Doubao.app" / "Contents"
    (app / "MacOS").mkdir(parents=True)
    import plistlib

    with open(app / "Info.plist", "wb") as fh:
        plistlib.dump(
            {"CFBundleShortVersionString": "2.35.8", "CFBundleIdentifier": "com.doubao"},
            fh,
        )
    exe = app / "MacOS" / "Doubao"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(localenv, "_MAC_APP_BASES", (str(tmp_path),))
    monkeypatch.delenv("DOUBAO_VERSION", raising=False)
    monkeypatch.delenv("DOUBAO_EXE", raising=False)
    return app


def test_mac_read_version_from_plist(mac_app):
    assert localenv.real_env().read_version() == "2.35.8"


def test_mac_locate_exe_from_bundle(mac_app):
    assert localenv.real_env().locate_exe() == mac_app / "MacOS" / "Doubao"


def test_mac_process_pids_parses_pgrep(monkeypatch):
    recorded = {}

    def fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout=b"2852\n2858\n")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(localenv.subprocess, "run", fake_run)
    assert localenv.real_env().process_pids() == [2852, 2858]
    assert "pgrep" in recorded["cmd"][0]


def test_mac_kill_pid_uses_sigkill(monkeypatch):
    recorded = {}

    def fake_kill(pid, sig):
        recorded["call"] = (pid, sig)

    import signal

    # 断言值与产品侧同源取 SIGKILL（Windows 无该属性，POSIX 上仍是真 SIGKILL）
    expected_sig = getattr(signal, "SIGKILL", 9)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(localenv.os, "kill", fake_kill)
    localenv.real_env().kill_pid(2852)
    assert recorded["call"] == (2852, expected_sig)


def test_mac_kill_pid_gone_is_success(monkeypatch):
    """进程已退出 = 杀净语义达成，不报错（taskkill 侧无此宽容——注册表平台差异）。"""
    import signal

    def gone(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(localenv.os, "kill", gone)
    localenv.real_env().kill_pid(2852)  # 不抛即过


def test_mac_spawn_detached_new_session(monkeypatch):
    recorded = {}

    def fake_popen(cmd, **kwargs):
        recorded["kwargs"] = kwargs
        return types.SimpleNamespace(pid=1)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(localenv.subprocess, "Popen", fake_popen)
    localenv.real_env().spawn_detached(Path("/Applications/Doubao.app/Contents/MacOS/Doubao"))
    assert recorded["kwargs"].get("start_new_session") is True  # 脱离父进程组
    assert "creationflags" not in recorded["kwargs"]


# --- 卸载注册表口径（PROTOCOL §1 实测定稿：子键名 Doubao*；DisplayName=豆包；
#     DisplayIcon 带引号指向 icon.ico）——fake winreg 注入，仅 Windows 跑 ---


def _fake_winreg(monkeypatch, entries: dict[str, dict[str, str]]) -> None:
    """winreg 假模块：entries = {子键名: {值名: 值}}。"""

    class FakeEntry:
        def __init__(self, values: dict[str, str]) -> None:
            self.values = values

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeRoot:
        names = list(entries)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    root = FakeRoot()

    class WR:
        HKEY_CURRENT_USER = object()
        KEY_READ = 0

        @staticmethod
        def OpenKey(root_key, path, reserved=0, access=0):
            if isinstance(path, str) and path.endswith("Uninstall"):
                return root
            return FakeEntry(entries[path])

        @staticmethod
        def EnumKey(key, index):
            if index >= len(key.names):
                raise OSError("end")
            return key.names[index]

        @staticmethod
        def QueryValueEx(entry, name):
            if name not in entry.values:
                raise OSError("missing")
            return entry.values[name], None

    monkeypatch.setitem(sys.modules, "winreg", WR)


@pytest.mark.skipif(sys.platform != "win32", reason="卸载注册表仅 Windows")
def test_registry_version_matches_subkey_with_cn_display(monkeypatch):
    """真机口径：子键 Doubao + DisplayName=豆包 → DisplayVersion 必须读到。"""
    _fake_winreg(monkeypatch, {
        "Doubao": {"DisplayName": "豆包", "DisplayVersion": "2.35.8"},
        "Other": {"DisplayName": "OtherApp", "DisplayVersion": "9.9.9"},
    })
    assert localenv.real_env().read_version() == "2.35.8"


@pytest.mark.skipif(sys.platform != "win32", reason="卸载注册表仅 Windows")
def test_registry_install_root_strips_quoted_icon(monkeypatch, tmp_path):
    """真机口径：DisplayIcon 形如 "D:\\...\\icon.ico"（带引号）→ 剥引号取父目录，
    exe 候选 = <root>/app/Doubao.exe。"""
    app_exe = tmp_path / "Doubao" / "app" / "Doubao.exe"
    app_exe.parent.mkdir(parents=True)
    app_exe.write_bytes(b"MZ")
    _fake_winreg(monkeypatch, {
        "Doubao": {
            "DisplayName": "豆包",
            "DisplayVersion": "2.35.8",
            "DisplayIcon": f'"{tmp_path / "Doubao" / "icon.ico"}"',
        },
    })
    assert localenv.real_env().locate_exe() == app_exe
