"""localenv offline tests: override precedence / default directories / registry fallback / DisplayIcon three forms."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from butler_connectors.workbuddy_cn import localenv
from butler_connectors.workbuddy_cn.localenv import (
    InvalidOverride,
    WorkbuddyEnv,
    _exe_from_entry,
    _locate_runtime_candidates,
    _registry_runtime_candidates,
    real_env,
)


def test_env_override_hits_file(tmp_path, monkeypatch):
    exe = tmp_path / "WorkBuddyAI.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("WORKBUDDY_EXE", str(exe))
    assert _locate_runtime_candidates() == [exe]


def test_env_override_expands_vars(tmp_path, monkeypatch):
    exe = tmp_path / "WorkBuddy.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("WORKBUDDY_EXE", "%MY_ROOT%/WorkBuddy.exe")
    monkeypatch.setenv("MY_ROOT", str(tmp_path))
    assert _locate_runtime_candidates() == [exe]


def test_env_override_invalid_raises(monkeypatch):
    monkeypatch.setenv("WORKBUDDY_EXE", "relative/path.exe")
    with pytest.raises(InvalidOverride, match="WORKBUDDY_EXE"):
        _locate_runtime_candidates()


@pytest.mark.skipif(sys.platform != "win32", reason="default directory probing only exists on win")
def test_default_dir_hit_no_registry(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBUDDY_EXE", raising=False)
    target = tmp_path / "Programs" / "WorkBuddyAI" / "WorkBuddyAI.exe"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    def must_not_read():
        raise AssertionError("should not read the registry when default directories hit")

    monkeypatch.setattr(localenv, "_registry_runtime_candidates", must_not_read)
    assert _locate_runtime_candidates() == [target]


def test_registry_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBUDDY_EXE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    # darwin：默认 .platform 束路径指到空目录（真机装了客户端时默认分支会命中，前提必须显式钉死）
    monkeypatch.setattr(localenv, "_MAC_APP_BASES", (str(tmp_path / "no-such-apps"),))
    exe = tmp_path / "WorkBuddyAI.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(localenv, "_registry_entries", lambda: [{"DisplayIcon": str(exe)}])
    assert _locate_runtime_candidates() == [exe]


def test_exe_from_entry_displayicon_forms(tmp_path):
    exe = tmp_path / "WorkBuddyAI.exe"
    exe.write_bytes(b"MZ")
    assert _exe_from_entry({"DisplayIcon": f"{exe},0"}) == exe  # with icon index
    assert _exe_from_entry({"DisplayIcon": f"{exe},-3"}) == exe  # negative index
    assert _exe_from_entry({"DisplayIcon": str(exe)}) == exe  # bare exe
    assert _exe_from_entry({"DisplayIcon": f'"{exe}"'}) == exe  # quoted
    # InstallLocation non-empty tried first (pointing to directory → append both names)
    assert _exe_from_entry({"InstallLocation": str(tmp_path), "DisplayIcon": "ghost"}) == exe


def test_displayicon_dir_joins_names(tmp_path):
    (tmp_path / "WorkBuddy.exe").write_bytes(b"MZ")
    assert _exe_from_entry({"DisplayIcon": str(tmp_path)}) == tmp_path / "WorkBuddy.exe"


def test_exe_from_entry_none_or_passthrough():
    assert _exe_from_entry({}) is None
    # suffixed exe not existing is not judged here (unified is_file filter in _registry_runtime_candidates)
    assert _exe_from_entry({"DisplayIcon": "D:/nope/WorkBuddyAI.exe"}) == Path("D:/nope/WorkBuddyAI.exe")


@pytest.mark.skipif(sys.platform != "win32", reason="normcase dedupe semantics only hold on win")
def test_registry_candidates_dedup_normcase(tmp_path, monkeypatch):
    exe = tmp_path / "WorkBuddyAI.exe"
    exe.write_bytes(b"MZ")
    entries = [
        {"DisplayIcon": str(exe).upper()},
        {"DisplayIcon": str(exe)},  # only differs by case → normcase dedupe
        {"DisplayIcon": str(tmp_path / "Ghost.exe")},  # nonexistent → is_file filter
    ]
    monkeypatch.setattr(localenv, "_registry_entries", lambda: entries)
    assert _registry_runtime_candidates() == [exe]


def test_env_bundle_injectable():
    env = WorkbuddyEnv(locate_runtime_candidates=lambda: [Path("a.exe")])
    assert env.locate_runtime_candidates() == [Path("a.exe")]
    assert real_env().locate_runtime_candidates is localenv._locate_runtime_candidates


def _fake_winreg(icon_dir: Path):
    """Three-hive Uninstall fake: HKCU has one WorkBuddy AI entry + one unrelated entry; both HKLM hives are missing."""
    import types

    mod = types.ModuleType("winreg")
    hkcu, hklm = 0x80000001, 0x80000002
    mod.HKEY_CURRENT_USER = hkcu
    mod.HKEY_LOCAL_MACHINE = hklm

    class FakeKey:
        """模拟真 PyHKEY：with 退出即关闭，关后再 QueryValueEx 抛 OSError——
        回归钉（真机验收抓过：with 块内只读 DisplayName、关后才读其余值 = 全丢）。"""

        def __init__(self, children=None, values=None):
            self.children = children or {}
            self.values = values or {}
            self.closed = False

        def __enter__(self):
            self.closed = False
            return self

        def __exit__(self, *exc):
            self.closed = True
            return False

    uninstall = FakeKey(
        children={
            "WorkBuddy AI": FakeKey(
                values={
                    "DisplayName": "WorkBuddy AI 5.9.4",
                    "DisplayIcon": f"{icon_dir}\\WorkBuddyAI.exe,0",
                }
            ),
            "Other Platform": FakeKey(
                values={"DisplayName": "Other Platform", "DisplayIcon": f"{icon_dir}\\other.exe"}
            ),
        }
    )
    uninstall_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    tree = {(hkcu, uninstall_path): uninstall}  # both HKLM hives missing → OSError tolerance path

    def OpenKey(hive, path):
        if isinstance(hive, FakeKey):
            child = hive.children.get(path)
            if child is None:
                raise OSError("no such subkey")
            child.closed = False  # 每次打开都是新句柄
            return child
        key = tree.get((hive, path))
        if key is None:
            raise OSError("no such key")
        key.closed = False
        return key

    def EnumKey(key, index):
        names = list(key.children)
        if index >= len(names):
            raise OSError("no more subkeys")
        return names[index]

    def QueryValueEx(key, name):
        if getattr(key, "closed", False):
            raise OSError("handle is closed")  # 真 winreg 语义：句柄关闭即失效
        if name not in key.values:
            raise OSError("value not found")
        return key.values[name], 1

    mod.OpenKey = OpenKey
    mod.EnumKey = EnumKey
    mod.QueryValueEx = QueryValueEx
    return mod


@pytest.mark.skipif(sys.platform != "win32", reason="registry candidate collection only exists on win")
def test_fake_winreg_prefix_match_and_hive_tolerance(tmp_path, monkeypatch):
    exe = tmp_path / "WorkBuddyAI.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.delenv("WORKBUDDY_EXE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(tmp_path))
    entries = localenv._registry_entries()
    assert len(entries) == 1  # Other Platform does not match the prefix; HKLM hive missing is tolerated
    assert localenv._registry_runtime_candidates() == [exe]  # "WorkBuddy AI" variant matched (old repo regex couldn't)


# --- mac .platform bundle branch (2026-11-12 verified live: probe electron 37.10.3 + decrypt full chain passes) ---


def _write_mac_bundle(root: Path, name: str) -> Path:
    exe = root / name / "Contents" / "MacOS" / "Electron"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    return exe


def _mac_platform(monkeypatch, *bases: str) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(localenv, "_MAC_APP_BASES", bases)
    monkeypatch.delenv("WORKBUDDY_EXE", raising=False)


def test_mac_candidates_from_bundle(tmp_path, monkeypatch):
    exe = _write_mac_bundle(tmp_path, "WorkBuddy.platform")
    _mac_platform(monkeypatch, str(tmp_path))
    assert _locate_runtime_candidates() == [exe]


def test_mac_ai_variant_bundle(tmp_path, monkeypatch):
    exe = _write_mac_bundle(tmp_path, "WorkBuddyAI.platform")
    _mac_platform(monkeypatch, str(tmp_path))
    assert _locate_runtime_candidates() == [exe]


def test_mac_no_bundle_empty_candidates(tmp_path, monkeypatch):
    _mac_platform(monkeypatch, str(tmp_path))
    assert _locate_runtime_candidates() == []  # all miss → empty table, caller reports "not located" explicitly


def test_mac_apps_root_before_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    apps = tmp_path / "apps"
    exe = _write_mac_bundle(apps, "WorkBuddy.platform")
    _mac_platform(monkeypatch, str(apps), str(home))
    assert _locate_runtime_candidates() == [exe]


def test_mac_override_wins_over_bundle(tmp_path, monkeypatch):
    _write_mac_bundle(tmp_path, "WorkBuddy.platform")
    override = tmp_path / "other" / "Electron"
    override.parent.mkdir(parents=True)
    override.write_bytes(b"MZ")
    _mac_platform(monkeypatch, str(tmp_path))
    monkeypatch.setenv("WORKBUDDY_EXE", str(override))
    assert _locate_runtime_candidates() == [override]
